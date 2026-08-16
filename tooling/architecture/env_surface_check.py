#!/usr/bin/env python3


from __future__ import annotations

import argparse
import ast
import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _orm_layer_scope import SCOPE
from _orm_layer_scope import iter_scope_files as _iter_scope_files
from _repo_root import find_odoo_root

ADR = "0029"

REPO_ROOT = find_odoo_root(Path(__file__).resolve(), tool="env_surface_check")
CORE = REPO_ROOT / "odoo"
ENVIRONMENT_PY = CORE / "orm" / "runtime" / "environment.py"

__all__ = ["SCOPE", "check", "environment_members", "iter_scope_files"]

SANCTIONED_PRIVATE: frozenset[str] = frozenset({"_", "_core"})


@dataclass(frozen=True)
class Known:
    path: str
    attr: str
    reason: str


_MEMO_REASON = (
    "Hot-path read of the Field._get_cache memo. Guarded by try/except KeyError "
    "with a self._get_cache(env) fallback, so an unmaterialised cached_property "
    "is handled. Debt, not a defect: the __dict__ string-key form is opaque to "
    "refactoring tools, which is precisely what this checker now compensates for."
)

KNOWN_VIOLATIONS: tuple[Known, ...] = (
    Known("odoo/orm/fields/base.py", "_field_cache_memo", _MEMO_REASON),
    Known("odoo/orm/fields/textual.py", "_field_cache_memo", _MEMO_REASON),
    Known("odoo/orm/fields/relational/many2one.py", "_field_cache_memo", _MEMO_REASON),
    Known(
        "odoo/orm/fields/_field_metadata.py",
        "_field_depends_context",
        "Field._is_context_dependent() derives the per-field context "
        "dependency. Candidate for promotion to a public Environment accessor. "
        "Moved here from fields/base.py when the column-shape cluster was "
        "extracted onto _FieldMetadataMixin to break the _field_convert <-> "
        "base.py cycle; the reach is unchanged, only its file.",
    ),
    Known(
        "odoo/orm/models/mixins/cache.py",
        "_field_depends_context",
        "Same accessor, from Layer 2. Promote both together.",
    ),
    Known(
        "odoo/orm/fields/_field_metadata.py",
        "_ir_defaults",
        "Field._company_dependent_fallback_raw() reads model defaults for the "
        "company-dependent fallback. Belongs behind a public accessor. Moved "
        "here from fields/base.py with _is_context_dependent, same extraction.",
    ),
    Known(
        "odoo/orm/fields/textual.py",
        "_lang",
        "Translated-field language resolution needs the raw (possibly '_'-"
        "prefixed) lang, which env.lang deliberately normalises away.",
    ),
    Known(
        "odoo/orm/models/mixins/create.py",
        "_context_defaults",
        "create() applies default_<name> context keys. Derived once on the "
        "Environment by design; the accessor should be public.",
    ),
)


@dataclass
class Reach:
    path: str
    layer: str
    attr: str
    lineno: int
    via_dict: bool = False

    @property
    def is_private(self) -> bool:
        return self.attr.startswith("_")


@dataclass
class Report:
    reaches: list[Reach] = field(default_factory=list)
    new: list[Reach] = field(default_factory=list)
    known: list[Reach] = field(default_factory=list)
    unknown_members: list[Reach] = field(default_factory=list)
    env_members: set[str] = field(default_factory=set)

    @property
    def ok(self) -> bool:
        return not self.new and not self.unknown_members


class _EnvReachCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.hits: list[tuple[str, int, bool]] = []

    @staticmethod
    def _is_env(node: ast.expr) -> bool:
        return (isinstance(node, ast.Attribute) and node.attr == "env") or (
            isinstance(node, ast.Name) and node.id == "env"
        )

    def visit_Subscript(self, node: ast.Subscript) -> None:
        value = node.value
        if (
            isinstance(value, ast.Attribute)
            and value.attr == "__dict__"
            and self._is_env(value.value)
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, str)
        ):
            self.hits.append((node.slice.value, node.lineno, True))
            return
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if self._is_env(node.value):
            self.hits.append((node.attr, node.lineno, False))
        self.generic_visit(node)


def environment_members(source: str | None = None) -> set[str]:

    text = source if source is not None else ENVIRONMENT_PY.read_text(encoding="utf-8")
    members: set[str] = set(dir(Mapping))
    for node in ast.walk(ast.parse(text)):
        if not (isinstance(node, ast.ClassDef) and node.name == "Environment"):
            continue
        for stmt in node.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                members.add(stmt.name)
            elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                members.add(stmt.target.id)
            elif isinstance(stmt, ast.Assign):
                for tgt in stmt.targets:
                    if isinstance(tgt, ast.Name):
                        members.add(tgt.id)
            elif isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
                continue
        for stmt in node.body:
            if (
                isinstance(stmt, ast.Assign)
                and any(
                    isinstance(t, ast.Name) and t.id == "__slots__"
                    for t in stmt.targets
                )
                and isinstance(stmt.value, (ast.Tuple, ast.List))
            ):
                for elt in stmt.value.elts:
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                        members.add(elt.value)
    return members


def iter_scope_files() -> list[tuple[Path, str]]:
    return _iter_scope_files(CORE)


def _is_known(path: str, attr: str) -> bool:
    return any(k.path == path and k.attr == attr for k in KNOWN_VIOLATIONS)


def check(files: list[tuple[Path, str]] | None = None) -> Report:
    report = Report(env_members=environment_members())
    for path, layer in files if files is not None else iter_scope_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        collector = _EnvReachCollector()
        collector.visit(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
        for attr, lineno, via_dict in collector.hits:
            reach = Reach(rel, layer, attr, lineno, via_dict)
            report.reaches.append(reach)
            if attr not in report.env_members and not attr.startswith("__"):
                report.unknown_members.append(reach)
            if reach.is_private and attr not in SANCTIONED_PRIVATE:
                if _is_known(rel, attr):
                    report.known.append(reach)
                else:
                    report.new.append(reach)
            elif layer == "components":
                report.new.append(reach)
    return report


def _render(report: Report) -> str:
    lines = ["Environment surface check", "=" * 64]
    by_layer: dict[str, dict[str, set[str]]] = {}
    for r in report.reaches:
        pkg = r.path.split("/")[2] if r.path.startswith("odoo/orm/") else r.path
        bucket = by_layer.setdefault(f"{r.layer} ({pkg})", {"pub": set(), "prv": set()})
        bucket["prv" if r.is_private else "pub"].add(r.attr)
    for name in sorted(by_layer):
        b = by_layer[name]
        lines.append(
            f"  {name:26s} public: {len(b['pub']):3d}   private: {len(b['prv']):2d}"
        )
    lines.append("-" * 64)
    lines.append(f"Environment members resolved: {len(report.env_members)}")
    lines.append(f"total env reaches: {len(report.reaches)}")

    if report.unknown_members:
        lines.append("\nMEMBERS THAT DO NOT EXIST ON Environment:")
        for r in report.unknown_members:
            how = ' via __dict__["..."]' if r.via_dict else ""
            lines.append(f"  {r.path}:{r.lineno}  env.{r.attr}{how}")
    if report.new:
        lines.append("\nNEW unsanctioned reaches:")
        lines.extend(
            f"  [{r.layer}] {r.path}:{r.lineno}  env.{r.attr}" for r in report.new
        )
    if report.known:
        lines.append(f"\n{len(report.known)} known reach(es) tolerated (tracked debt):")
        for r in sorted(report.known, key=lambda x: (x.path, x.lineno)):
            how = ' via __dict__["..."]' if r.via_dict else ""
            lines.append(f"  {r.path}:{r.lineno}  env.{r.attr}{how}")
    lines.append("")
    lines.append(
        "Environment surface intact. ✓" if report.ok else "FAILED: the env seam moved."
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gate the Layer -> runtime env seam.")
    parser.add_argument("--check", action="store_true", help="CI mode: exit 1 on drift")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    report = check()
    if args.json:
        print(
            json.dumps(
                {
                    "ok": report.ok,
                    "total_reaches": len(report.reaches),
                    "new": [
                        {"path": r.path, "line": r.lineno, "attr": r.attr}
                        for r in report.new
                    ],
                    "unknown_members": [
                        {"path": r.path, "line": r.lineno, "attr": r.attr}
                        for r in report.unknown_members
                    ],
                    "known": len(report.known),
                },
                indent=2,
            )
        )
    else:
        print(_render(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())

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

REPO_ROOT = find_odoo_root(Path(__file__).resolve(), tool="env_surface_check")
CORE = REPO_ROOT / "odoo"
ENVIRONMENT_PY = CORE / "orm" / "runtime" / "environment.py"

__all__ = [
    "LAYER1_CORE_MEMBERS",
    "LAYER1_CORE_REACHES",
    "SCOPE",
    "check",
    "environment_members",
    "iter_scope_files",
]

SANCTIONED_PRIVATE: frozenset[str] = frozenset({"_", "_core"})

# Layer 1's whole view of the cache and compute engine is the named OrmCore
# methods below, reached as ``env._core.<member>`` or through a local bound from
# ``env._core``. The pair is exact in both directions: a new member or a new
# reach moves it and must be re-banked here, the same way a removed one must.
LAYER1_CORE_MEMBERS: frozenset[str] = frozenset(
    {
        "add_patch",
        "all_cached_ids",
        "all_context_cached_ids",
        "get_context_data",
        "get_context_data_or_none",
        "get_dirty",
        "get_field_data",
        "get_field_data_or_none",
        "get_patches",
        "has_pending_field",
        "invalidate",
        "is_protected",
        "iter_context_caches",
        "mark_dirty",
        "pending_ids",
        "protected_ids",
    }
)
LAYER1_CORE_REACHES: int = 33


@dataclass(frozen=True)
class Known:
    path: str
    attr: str
    reason: str


_MEMO_REASON = (
    "Hot-path read of the Field._get_cache memo, in the one place it is spelled: "
    "_prepare_fast_get builds every fast __get__ from it. Guarded by try/except "
    "KeyError with a self._get_uncached fallback, so an unmaterialised "
    "cached_property is handled. Debt, not a defect: the __dict__ string-key form "
    "is opaque to refactoring tools, which is precisely what this checker now "
    "compensates for."
)

KNOWN_VIOLATIONS: tuple[Known, ...] = (
    Known("odoo/orm/fields/base.py", "_field_cache_memo", _MEMO_REASON),
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
        "odoo/orm/fields/_field_translation.py",
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


@dataclass(frozen=True)
class CoreReach:
    path: str
    layer: str
    member: str
    lineno: int


@dataclass
class Report:
    reaches: list[Reach] = field(default_factory=list)
    new: list[Reach] = field(default_factory=list)
    known: list[Reach] = field(default_factory=list)
    unknown_members: list[Reach] = field(default_factory=list)
    env_members: set[str] = field(default_factory=set)
    core_reaches: list[CoreReach] = field(default_factory=list)
    core_drift: list[str] = field(default_factory=list)

    @property
    def layer1_core_reaches(self) -> list[CoreReach]:
        return [r for r in self.core_reaches if r.layer == "Layer 1"]

    @property
    def ok(self) -> bool:
        return not self.new and not self.unknown_members and not self.core_drift


class _EnvReachCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.hits: list[tuple[str, int, bool]] = []
        self.core_hits: list[tuple[str, int]] = []
        self.core_aliases: set[str] = set()

    @staticmethod
    def _is_env(node: ast.expr) -> bool:
        return (isinstance(node, ast.Attribute) and node.attr == "env") or (
            isinstance(node, ast.Name) and node.id == "env"
        )

    def _is_core(self, node: ast.expr) -> bool:
        return (
            isinstance(node, ast.Attribute)
            and node.attr == "_core"
            and self._is_env(node.value)
        ) or (isinstance(node, ast.Name) and node.id in self.core_aliases)

    def visit(self, node: ast.AST) -> None:
        if isinstance(node, ast.Module):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Assign) and self._is_core(sub.value):
                    self.core_aliases.update(
                        t.id for t in sub.targets if isinstance(t, ast.Name)
                    )
        super().visit(node)

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
        elif self._is_core(node.value):
            self.core_hits.append((node.attr, node.lineno))
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


def _core_pin_drift(reaches: list[CoreReach]) -> list[str]:
    drift: list[str] = []
    members = {r.member for r in reaches}
    if len(reaches) != LAYER1_CORE_REACHES:
        drift.append(
            f"Layer 1 reaches env._core {len(reaches)} time(s); "
            f"LAYER1_CORE_REACHES pins {LAYER1_CORE_REACHES}"
        )
    for member in sorted(members - LAYER1_CORE_MEMBERS):
        where = [f"{r.path}:{r.lineno}" for r in reaches if r.member == member]
        drift.append(
            f"Layer 1 reaches env._core.{member}, not in LAYER1_CORE_MEMBERS: "
            + ", ".join(where)
        )
    drift.extend(
        f"LAYER1_CORE_MEMBERS pins {member!r} but Layer 1 no longer reaches it"
        for member in sorted(LAYER1_CORE_MEMBERS - members)
    )
    return drift


def check(files: list[tuple[Path, str]] | None = None) -> Report:
    report = Report(env_members=environment_members())
    for path, layer in files if files is not None else iter_scope_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        collector = _EnvReachCollector()
        collector.visit(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
        report.core_reaches.extend(
            CoreReach(rel, layer, member, lineno)
            for member, lineno in collector.core_hits
        )
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
    if files is None:
        report.core_drift = _core_pin_drift(report.layer1_core_reaches)
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
    layer1_core = report.layer1_core_reaches
    lines.append(
        f"Layer 1 -> env._core: {len(layer1_core)} reaches through "
        f"{len({r.member for r in layer1_core})} members "
        f"(pinned: {LAYER1_CORE_REACHES} / {len(LAYER1_CORE_MEMBERS)})"
    )
    if report.core_drift:
        lines.append("\nLAYER 1 env._core PIN MOVED:")
        lines.extend(f"  {line}" for line in report.core_drift)

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
                    "layer1_core_reaches": len(report.layer1_core_reaches),
                    "core_drift": report.core_drift,
                },
                indent=2,
            )
        )
    else:
        print(_render(report))
    return 1 if (not report.ok and args.check) else 0


if __name__ == "__main__":
    sys.exit(main())

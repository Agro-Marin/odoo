#!/usr/bin/env python3
"""env_surface_check.py — drift-zero gate on the Layer -> runtime ``env`` seam.

``layer_check.py`` enforces the ORM layer model on **import** edges:
``orm-layer1-below-models-and-runtime`` and ``orm-models-below-runtime`` fail CI
if ``orm/fields``, ``orm/domain`` or ``orm/models`` import ``orm/runtime``. They
are clean, and they always will be — because that is not how those layers reach
the runtime. They reach it through ``self.env``, on every call, and an
``env.registry`` or ``env._field_cache_memo`` produces **no import edge at all**.

So the ORM's widest cross-layer dependency is invisible to the checker that
guards everything around it. ``mixin_coupling_check.py`` exists for exactly this
reason one level down (mixins collaborating through ``self``); this is the same
argument applied to the seam between the layers and Layer 3.

The measurement that motivated this gate: **Layer 1 — the layer declared
*furthest below* the runtime — is the heaviest consumer of the runtime's
private internals, wider than Layer 2.**

    orm/fields        21 public env members + 4 unsanctioned private (10 accesses)
    orm/models        23 public env members + 2 unsanctioned private ( 3 accesses)
    orm/domain         4 public env members + 0
    orm/registration   2 public env members + 0
    orm/components                        0 + 0   (its purity claim,
                                                   independently confirmed here)

Only the **private** figures are pinned against a live run
(``test_architecture_doc.TestRuntimeSurfaceFigures``). The public ones are
reported, not ratcheted — and had already drifted (fields was written as 19,
models as 21) before anyone noticed, which is the argument for the pinning
rather than against it. ``orm/registration`` appears at all only because the
scope stopped being ``orm/models`` alone; see ``_orm_layer_scope``.

The distinct unsanctioned private names across the whole ORM number FIVE, not
six: ``_field_depends_context`` is reached from both packages. Counting that
union as ``orm/fields``' own figure is the arithmetic slip this note used to
make (and ARCHITECTURE.md copied); ``test_env_surface_check`` now derives both
numbers from a live run so the two cannot drift apart again. The inversion the
gate exists to show is unaffected -- 4 > 2 on members, 10 > 3 on accesses.

WHAT IS ENFORCED
----------------

1. **No unsanctioned private access.** ``env.<_name>`` from Layer 0/1/2 is a
   violation unless it is one of ``SANCTIONED_PRIVATE`` or pinned in
   ``KNOWN_VIOLATIONS``. Two private names are sanctioned by design:

   * ``env._``     — the gettext translation helper. Private *spelling*, public
                     intent; the leading underscore is the i18n convention.
   * ``env._core`` — the curated id-level cache/compute facade (``OrmCore``).
                     It is deliberately the sanctioned route for framework ORM
                     code, and its whole purpose is to keep the raw
                     ``FieldCache``/``ComputeEngine`` private to ``Transaction``.

2. **Every referenced member must exist on ``Environment``.** This is the part
   nothing currently does, and it is why the gate earns its place. Four call
   sites reach the cache memo as ``env.__dict__["_field_cache_memo"]`` — a
   *string key*, to skip the ``cached_property`` descriptor on a hot path. That
   is a legitimate optimisation and it is correctly ``try/except KeyError``
   guarded, but it is invisible to every static tool in the repo: renaming
   ``Environment._field_cache_memo`` would leave those four sites silently
   reading a key that can never exist, and the ``except KeyError`` fallback
   would quietly turn the fast path into a permanent slow path. **No test would
   fail.** This checker resolves those string keys and validates them like any
   other attribute.

``components/`` is included in the scan with an empty allow-list: it must reach
``env`` for nothing at all, which is the runtime half of the purity claim that
``orm-components-are-pure-python`` makes about imports.

WHAT IS NOT ENFORCED
--------------------

The *public* env surface is reported, not ratcheted. Layer 1 using
``env.context`` is the design working as intended, and a gate that fired on a
19th public member would punish ordinary work. Private reach and name validity
are the invariants; width is a metric.

USAGE
-----

  python tooling/architecture/env_surface_check.py            # report
  python tooling/architecture/env_surface_check.py --check    # CI: exit 1
  python tooling/architecture/env_surface_check.py --json

exit 0 — no new violations
exit 1 — a new private reach, or a member that does not exist on Environment
exit 2 — usage error
"""

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

#: Re-exported for callers and for the self-test. The scope itself lives in
#: ``_orm_layer_scope`` because ``pool_surface_check`` needs the identical
#: answer to "what is Layer N" -- the two used to keep byte-identical copies
#: under a comment claiming they were "deliberately identical", which nothing
#: enforced and which had already lapsed in two places.
__all__ = ["SCOPE", "check", "environment_members", "iter_scope_files"]

#: Private ``Environment`` members that lower layers may use. See the module
#: docstring for why each one is here.
SANCTIONED_PRIVATE: frozenset[str] = frozenset({"_", "_core"})


@dataclass(frozen=True)
class Known:
    """A tolerated private reach, pinned so it stays visible and cannot spread."""

    path: str  # repo-relative source file
    attr: str  # the private Environment member it reaches
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
        "odoo/orm/fields/base.py",
        "_field_depends_context",
        "Field.cache_key() derives the per-field context dependency. Candidate "
        "for promotion to a public Environment accessor.",
    ),
    Known(
        "odoo/orm/models/mixins/cache.py",
        "_field_depends_context",
        "Same accessor, from Layer 2. Promote both together.",
    ),
    Known(
        "odoo/orm/fields/base.py",
        "_ir_defaults",
        "Field.default_for() reads model defaults to dedup against the write "
        "side. Belongs behind a public accessor.",
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
    """Collect ``<x>.env.<attr>`` / ``env.<attr>`` reads.

    Heuristic, and deliberately so: within ``odoo/orm/**`` an attribute named
    ``env`` is the Environment. The alternative — resolving types — buys nothing
    here and would make the gate unmaintainable.
    """

    def __init__(self) -> None:
        self.hits: list[tuple[str, int, bool]] = []

    @staticmethod
    def _is_env(node: ast.expr) -> bool:
        return (isinstance(node, ast.Attribute) and node.attr == "env") or (
            isinstance(node, ast.Name) and node.id == "env"
        )

    def visit_Subscript(self, node: ast.Subscript) -> None:
        # ``env.__dict__["_field_cache_memo"]`` — resolve the string key to the
        # member it actually names, instead of recording an opaque ``__dict__``.
        value = node.value
        if (
            isinstance(value, ast.Attribute)
            and value.attr == "__dict__"
            and self._is_env(value.value)
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, str)
        ):
            self.hits.append((node.slice.value, node.lineno, True))
            return  # do not also record the bare ``__dict__`` attribute
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if self._is_env(node.value):
            self.hits.append((node.attr, node.lineno, False))
        self.generic_visit(node)


def environment_members(source: str | None = None) -> set[str]:
    """Every attribute reachable on an ``Environment`` instance.

    Class-body names (annotations, assignments, methods, ``@property`` and
    ``@functools.cached_property``) plus what it inherits from ``Mapping`` —
    ``env.get`` is used by Layers 1 and 2 and is defined by the ABC, not by
    ``Environment``, so omitting the base would produce false positives.
    """
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
        # ``__slots__ = ("cr", "uid", ...)`` if it is ever used here
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
            # (1) does the member exist at all?
            if attr not in report.env_members and not attr.startswith("__"):
                report.unknown_members.append(reach)
            # (2) unsanctioned private reach from below Layer 3?
            if reach.is_private and attr not in SANCTIONED_PRIVATE:
                if _is_known(rel, attr):
                    report.known.append(reach)
                else:
                    report.new.append(reach)
            # (3) components must reach env for nothing whatsoever
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

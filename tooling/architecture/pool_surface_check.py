#!/usr/bin/env python3
"""pool_surface_check.py — drift-zero gate on the Layer -> runtime ``pool`` seam.

The sibling of ``env_surface_check.py``, for the channel that argument missed.

``env_surface_check`` exists because ``layer_check`` reasons about imports, and
Layers 1 and 2 do not reach the runtime by importing it — they reach it through
``self.env``. Exactly the same is true of ``self.pool``: it **is** the
``Registry`` (``orm/models/metaclass.py``: ``pool: Registry | None``, imported
from ``..runtime``), so every ``model.pool.<member>`` is a Layer-N -> Layer-3
access that produces no import edge and moves no existing gate.

Measured when this checker landed — the same inversion ``env_surface_check`` was
built to expose, on a wider surface:

    orm/fields + orm/domain  (Layer 1)   30 accesses, 9 members, 5 subscripts
    orm/models               (Layer 2)   17 accesses, 11 members, 0 subscripts
    orm/components                        0 accesses  (its purity claim, again
                                                       independently confirmed)

Layer 1 — the layer declared *furthest below* the runtime — reaches the Registry
almost twice as often as Layer 2 does, and reaches one member Layer 2 never
touches: the private ``_relation_reflections``.

WHAT IS ENFORCED
----------------

1. **No unsanctioned private access.** ``pool.<_name>`` from Layer 0/1/2 is a
   violation unless pinned in :data:`KNOWN_VIOLATIONS`.

2. **Every referenced member must exist on ``Registry``.** ``pool: typing.Any``
   in ``mixins/_model_stubs.py`` is overridden by ``MetaModel.pool: Registry |
   None``, so mypy does check plain attribute reads today — but it cannot see
   which *layer* performed them, and it cannot see the lifecycle window below.

3. **``components/`` must not touch ``pool`` at all** — the runtime half of the
   purity claim ``orm-components-are-pure-python`` makes about imports.

WHY THE PRIVATE REACH IS WORSE THAN IT LOOKS
--------------------------------------------

``Registry._relation_reflections`` is not merely private. It is created inside
``Registry.init_models``' ``try:`` and ``del``-eted in its ``finally:``, so it
exists **only for the duration of that call**. ``orm/fields/relational/
many2many.py`` mutates it from Layer 1, which works solely because
``update_db`` runs inside that window via ``model._auto_init()``. Nothing
declares that ordering contract, and nothing would catch its violation except an
``AttributeError`` during module installation. Three sibling attributes
(``_post_init_queue``, ``_foreign_keys``, ``_is_install``) share the lifecycle
but are reached only through public methods (``post_init``, ``add_foreign_key``),
which is what this one should do too.

WHAT IS NOT ENFORCED
--------------------

The *public* pool surface is reported, not ratcheted — same rationale as
``env_surface_check``: Layer 1 consulting ``pool.field_inverses`` is the design
working, and a gate that fired on a 10th public member would punish ordinary
work. Private reach, name validity and the ``components`` zero are the
invariants; width is a metric.

USAGE
-----

  python tooling/architecture/pool_surface_check.py            # report
  python tooling/architecture/pool_surface_check.py --check    # CI: exit 1
  python tooling/architecture/pool_surface_check.py --json

exit 0 — no new violations
exit 1 — a new private reach, a member that does not exist, or components touching pool
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

REPO_ROOT = find_odoo_root(Path(__file__).resolve(), tool="pool_surface_check")
CORE = REPO_ROOT / "odoo"

#: ``Registry`` and the two mixins it is composed from. All three contribute
#: members, and ``Registry`` inherits ``Mapping`` (``pool.get``, ``pool.keys``…).
REGISTRY_SOURCES: tuple[Path, ...] = (
    CORE / "orm" / "runtime" / "registry.py",
    CORE / "orm" / "runtime" / "_registry_fields.py",
    CORE / "orm" / "runtime" / "_registry_schema.py",
    CORE / "orm" / "runtime" / "_registry_stubs.py",
)

#: Scanned packages and the ORM layer each sits at — deliberately identical to
#: ``env_surface_check.SCOPE`` so the two reports are comparable line for line.
SCOPE: dict[str, str] = {
    "orm/primitives.py": "Layer 0",
    "orm/parsing.py": "Layer 0",
    "orm/validation.py": "Layer 0",
    "orm/fields": "Layer 1",
    "orm/domain": "Layer 1",
    "orm/models": "Layer 2",
    "orm/components": "components",
}


@dataclass(frozen=True)
class Known:
    path: str
    attr: str
    reason: str


KNOWN_VIOLATIONS: tuple[Known, ...] = (
    Known(
        "odoo/orm/fields/relational/many2many.py",
        "_relation_reflections",
        "Layer 1 mutates a Registry attribute that only EXISTS between the try "
        "and the finally of Registry.init_models. Many2many.update_db records "
        "the relation table so ir.model.relation._reflect_relations can persist "
        "it. Debt with a clear fix: give Registry a public "
        "`record_relation_reflection(...)` method, as post_init/add_foreign_key "
        "already do for the sibling lifecycle attributes.",
    ),
    Known(
        "odoo/orm/models/mixins/recompute.py",
        "_ensure_field_triggers",
        "RecomputeMixin.modified() needs the trigger tree built before it can "
        "ask whether any modified field has dependents. Mild: the five other "
        "callers are all inside _RegistryFieldsMixin itself, which is the "
        "signal that this is an internal lazy-init hook. Every PUBLIC accessor "
        "(get_trigger_tree, get_dependent_fields, field_depends) already calls "
        "it first, so Layer 2 should reach one of those instead of priming the "
        "cache by hand.",
    ),
)


@dataclass
class Reach:
    path: str
    layer: str
    attr: str
    lineno: int
    subscript: bool = False

    @property
    def is_private(self) -> bool:
        # Dunders are protocol, not internals: ``pool[...]`` is recorded as
        # ``__getitem__`` and is the Mapping interface Registry publicly
        # implements, not a reach past its boundary.
        return self.attr.startswith("_") and not self.attr.startswith("__")


@dataclass
class Report:
    reaches: list[Reach] = field(default_factory=list)
    new: list[Reach] = field(default_factory=list)
    known: list[Reach] = field(default_factory=list)
    unknown_members: list[Reach] = field(default_factory=list)
    component_reaches: list[Reach] = field(default_factory=list)
    registry_members: set[str] = field(default_factory=set)

    @property
    def ok(self) -> bool:
        return not self.new and not self.unknown_members and not self.component_reaches


class _PoolReachCollector(ast.NodeVisitor):
    """Collect ``<x>.pool.<attr>`` and ``<x>.pool[...]`` reads.

    Heuristic on the receiver name, exactly as ``_EnvReachCollector`` is: within
    ``odoo/orm/**`` an attribute named ``pool`` is the Registry. (The connection
    pool in ``odoo/db/pool.py`` is never reached this way from the ORM — the
    scope below cannot see ``odoo/db`` at all.)
    """

    def __init__(self) -> None:
        self.hits: list[tuple[str, int, bool]] = []

    @staticmethod
    def _is_pool(node: ast.expr) -> bool:
        return (isinstance(node, ast.Attribute) and node.attr == "pool") or (
            isinstance(node, ast.Name) and node.id == "pool"
        )

    def visit_Subscript(self, node: ast.Subscript) -> None:
        # ``model.pool["res.partner"]`` — Registry.__getitem__, a model-class
        # lookup. Recorded separately: it is a *use* of the registry mapping
        # rather than a reach into its internals.
        if self._is_pool(node.value):
            self.hits.append(("__getitem__", node.lineno, True))
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if self._is_pool(node.value):
            self.hits.append((node.attr, node.lineno, False))
        self.generic_visit(node)


def registry_members(sources: tuple[Path, ...] | None = None) -> set[str]:
    """Every attribute reachable on a ``Registry`` instance.

    Class-body names across ``Registry`` and its mixins (annotations,
    assignments, methods, properties) **plus ``self.<name> = ...`` assignments
    inside their methods** — unlike ``Environment``, ``Registry`` creates several
    members imperatively (``_relation_reflections``, ``_post_init_queue``,
    ``_ordinary_tables``), and omitting those would report false "does not
    exist" failures. ``Mapping`` is included because ``Registry`` subclasses it.
    """
    members: set[str] = set(dir(Mapping))
    for path in sources if sources is not None else REGISTRY_SOURCES:
        if not path.is_file():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for stmt in node.body:
                if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    members.add(stmt.name)
                elif isinstance(stmt, ast.AnnAssign) and isinstance(
                    stmt.target, ast.Name
                ):
                    members.add(stmt.target.id)
                elif isinstance(stmt, ast.Assign):
                    for tgt in stmt.targets:
                        if isinstance(tgt, ast.Name):
                            members.add(tgt.id)
            # imperatively created members: ``self.<name> = ...`` / ``self.<name>: T = ...``
            for sub in ast.walk(node):
                targets: list[ast.expr] = []
                if isinstance(sub, ast.Assign):
                    targets = list(sub.targets)
                elif isinstance(sub, ast.AnnAssign):
                    targets = [sub.target]
                for tgt in targets:
                    if (
                        isinstance(tgt, ast.Attribute)
                        and isinstance(tgt.value, ast.Name)
                        and tgt.value.id == "self"
                    ):
                        members.add(tgt.attr)
    return members


def iter_scope_files() -> list[tuple[Path, str]]:
    out: list[tuple[Path, str]] = []
    for rel, layer in SCOPE.items():
        target = CORE / rel
        if target.is_dir():
            paths = sorted(target.rglob("*.py"))
        elif target.is_file():
            paths = [target]
        else:
            continue
        for p in paths:
            parts = p.relative_to(CORE).parts
            if "tests" in parts or "__pycache__" in parts or p.name.startswith("test_"):
                continue
            out.append((p, layer))
    return out


def _is_known(path: str, attr: str) -> bool:
    return any(k.path == path and k.attr == attr for k in KNOWN_VIOLATIONS)


def check(files: list[tuple[Path, str]] | None = None) -> Report:
    report = Report(registry_members=registry_members())
    for path, layer in files if files is not None else iter_scope_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        collector = _PoolReachCollector()
        collector.visit(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
        for attr, lineno, subscript in collector.hits:
            reach = Reach(rel, layer, attr, lineno, subscript)
            report.reaches.append(reach)
            if layer == "components":
                report.component_reaches.append(reach)
                continue
            if attr not in report.registry_members and not attr.startswith("__"):
                report.unknown_members.append(reach)
            if reach.is_private:
                (report.known if _is_known(rel, attr) else report.new).append(reach)
    return report


def _print_report(report: Report) -> None:
    print("Layer -> Registry surface (the `pool` seam)")
    print("=" * 64)
    by_layer: dict[str, list[Reach]] = {}
    for reach in report.reaches:
        by_layer.setdefault(reach.layer, []).append(reach)
    for layer in ("Layer 0", "Layer 1", "Layer 2", "components"):
        hits = by_layer.get(layer, [])
        attrs = {r.attr for r in hits if not r.subscript}
        subs = sum(1 for r in hits if r.subscript)
        privates = sorted({r.attr for r in hits if r.is_private})
        print(f"\n  {layer}: {len(hits)} accesses, {len(attrs)} members, {subs} subscripts")
        if attrs:
            print(f"    {sorted(attrs)}")
        if privates:
            print(f"    private: {privates}")
    if report.component_reaches:
        print("\n  ✗ components/ reached `pool` — it must reach it for nothing:")
        for r in report.component_reaches:
            print(f"      {r.path}:{r.lineno}  pool.{r.attr}")
    if report.unknown_members:
        print("\n  ✗ members that do not exist on Registry:")
        for r in report.unknown_members:
            print(f"      {r.path}:{r.lineno}  pool.{r.attr}")
    if report.new:
        print("\n  ✗ new unsanctioned private reaches:")
        for r in report.new:
            print(f"      {r.path}:{r.lineno}  pool.{r.attr}  [{r.layer}]")
    print("-" * 64)
    if report.known:
        print(f"tolerated private reaches: {len(report.known)} (pinned)")
    print("Registry surface intact. ✓" if report.ok else "Registry surface DRIFTED. ✗")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="CI mode: exit 1 on drift")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    report = check()
    if args.json:
        print(
            json.dumps(
                {
                    "reaches": [vars(r) for r in report.reaches],
                    "new": [vars(r) for r in report.new],
                    "known": [vars(r) for r in report.known],
                    "unknown_members": [vars(r) for r in report.unknown_members],
                    "component_reaches": [vars(r) for r in report.component_reaches],
                    "ok": report.ok,
                },
                indent=2,
            )
        )
    else:
        _print_report(report)
    return 0 if report.ok or not args.check else 1


if __name__ == "__main__":
    sys.exit(main())

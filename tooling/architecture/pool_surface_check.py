#!/usr/bin/env python3
"""pool_surface_check.py — drift-zero gate on the Layer -> runtime ``pool`` seam.

The sibling of ``env_surface_check.py``, for the channel that argument missed.

``env_surface_check`` exists because ``layer_check`` reasons about imports, and
Layers 1 and 2 do not reach the runtime by importing it — they reach it through
``self.env``. Exactly the same is true of ``self.pool``: it **is** the
``Registry`` (``orm/models/metaclass.py``: ``pool: Registry | None``, imported
from ``..runtime``), so every ``model.pool.<member>`` is a Layer-N -> Layer-3
access that produces no import edge and moves no existing gate.

Measured — the same inversion ``env_surface_check`` was built to expose, on a
wider surface:

    Layer 1  (fields, domain, _recordset, decorators)  30 accesses,  9 members
    Layer 2  (models, helpers, registration)           28 accesses, 15 members
    components                                          0 accesses  (its purity
                                                        claim, again confirmed)

Layer 1 — the layer declared *furthest below* the runtime — reaches the Registry
more often than Layer 2 and owns 5 of the 8 ``pool[<model>]`` subscripts, though
Layer 2 reaches more distinct members.

**These numbers are restated prose and will rot.** They are pinned against a
live run by ``test_architecture_doc.TestRuntimeSurfaceFigures``, which exists
because this docstring and ``ARCHITECTURE.md`` once agreed with each other and
with nothing else. The Layer-2 figures above already moved once, when the scope
stopped being ``orm/models`` alone — see ``_orm_layer_scope``.

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

WHY A PRIVATE REACH CAN BE WORSE THAN IT LOOKS
----------------------------------------------

This gate's first pinned violation is worth keeping as the worked example, now
that it is paid off. ``Registry._relation_reflections`` was not merely private:
it was created inside ``Registry.init_models``' ``try:`` and ``del``-eted in its
``finally:``, so it existed **only for the duration of that call**, and
``orm/fields/relational/many2many.py`` mutated it from Layer 1 -- which worked
solely because ``update_db`` runs inside that window via
``model._auto_init()``. Nothing declared the ordering, and nothing would have
caught a violation except an ``AttributeError`` during module installation.

Three siblings (``_post_init_queue``, ``_foreign_keys``, ``_is_install``)
shared the lifecycle; two were already reached through public methods
(``post_init``, ``add_foreign_key``), which is what this entry's remediation
note asked for.

Fixed 2026-08-09, and more thoroughly than the note proposed: all four became
one ``InitModelsPhase`` behind ``Registry.init_phase``, which raises a named
``RuntimeError`` outside the window rather than an ``AttributeError`` naming a
private attribute, and Layer 1 calls ``pool.add_relation_reflection(...)``. The
pin is what made that a scheduled fix against a written remediation instead of
a rediscovery.

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

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _orm_layer_scope import SCOPE
from _orm_layer_scope import iter_scope_files as _iter_scope_files
from _repo_root import find_odoo_root

ADR = "0029"

REPO_ROOT = find_odoo_root(Path(__file__).resolve(), tool="pool_surface_check")
CORE = REPO_ROOT / "odoo"

REGISTRY_SOURCES: tuple[Path, ...] = (
    CORE / "orm" / "runtime" / "registry.py",
    CORE / "orm" / "runtime" / "_registry_fields.py",
    CORE / "orm" / "runtime" / "_registry_schema.py",
    CORE / "orm" / "runtime" / "_registry_models.py",
    CORE / "orm" / "runtime" / "_registry_capabilities.py",
    CORE / "orm" / "runtime" / "_registry_init_phase.py",
    CORE / "orm" / "runtime" / "_registry_stubs.py",
)

REGISTRY_CLASSES: frozenset[str] = frozenset(
    {
        "Registry",
        "_RegistryFieldsMixin",
        "_RegistrySchemaMixin",
        "_RegistryModelsMixin",
        "_RegistryInitPhaseMixin",
        "_RegistryCapabilitiesMixin",
    }
)

__all__ = ["SCOPE", "check", "iter_scope_files", "registry_members"]


@dataclass(frozen=True)
class Known:
    path: str
    attr: str
    reason: str


KNOWN_VIOLATIONS: tuple[Known, ...] = (
    Known(
        "odoo/orm/registration.py",
        "_init_modules",
        "Model setup asks whether a module install is in flight before adding "
        "manual (ir.model.fields) fields. Registry.__init__ creates the set and "
        "the loader fills it, so this is the same lifecycle coupling "
        "_relation_reflections had before it was fixed: registration runs "
        "INSIDE registry setup and "
        "reads its host's in-progress state. Fix is a public predicate "
        "(`Registry.is_initialising_modules()`), which also documents the "
        "ordering contract that is currently implicit.",
    ),
    Known(
        "odoo/orm/registration.py",
        "_database_translated_fields",
        "Reflection data the Registry loaded from ir_model_fields, consumed by "
        "_patch_translate_field to keep a field's translate= in step with what "
        "the database already stores. Read twice (membership, then the value). "
        "Belongs behind a public accessor pair on Registry alongside "
        "_database_company_dependent_fields -- promote both together.",
    ),
    Known(
        "odoo/orm/registration.py",
        "_database_company_dependent_fields",
        "The company_dependent half of the same reflection lookup, used by "
        "_patch_company_dependent_field. Same fix as "
        "_database_translated_fields; they are one concept split across two "
        "attributes and should get one public accessor.",
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
    def __init__(self) -> None:
        self.hits: list[tuple[str, int, bool]] = []

    @staticmethod
    def _is_pool(node: ast.expr) -> bool:
        return (isinstance(node, ast.Attribute) and node.attr == "pool") or (
            isinstance(node, ast.Name) and node.id == "pool"
        )

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if self._is_pool(node.value):
            self.hits.append(("__getitem__", node.lineno, True))
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if self._is_pool(node.value):
            self.hits.append((node.attr, node.lineno, False))
        self.generic_visit(node)


def registry_members(sources: tuple[Path, ...] | None = None) -> set[str]:

    members: set[str] = set(dir(Mapping))
    for path in sources if sources is not None else REGISTRY_SOURCES:
        if not path.is_file():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if node.name not in REGISTRY_CLASSES:
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
    return _iter_scope_files(CORE)


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
    # Refuse a scan that reached nothing rather than report the seam intact.
    # `registry_members()` skips a missing REGISTRY_SOURCES file and
    # `iter_scope_files()` yields nothing for an emptied tree, so an empty
    # checkout printed "Registry surface intact. ✓" and exited 0 -- the exact
    # failure `test_every_gate_refuses_an_empty_tree` exists to catch, which
    # never saw it because the probe died on an import before reaching here.
    # Layer 1 alone holds hundreds of reaches; zero has never held.
    if files is None and not report.reaches:
        raise SystemExit(
            "pool_surface_check: no Registry reach found in any scoped file — "
            "the scan found no inputs; refusing to report the seam intact."
        )
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
        print(
            f"\n  {layer}: {len(hits)} accesses, {len(attrs)} members, {subs} subscripts"
        )
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

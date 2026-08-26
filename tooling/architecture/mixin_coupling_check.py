#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

ADR = "0024"

ROOT = find_odoo_root(Path(__file__).resolve(), tool="mixin_coupling_check")
MODELS = ROOT / "odoo" / "orm" / "models"
MIXINS = MODELS / "mixins"

BASE_UNIT = "base.py"

EXCLUDED_UNITS = frozenset({"_model_stubs", "_crud_common", "__init__"})

DUPLICATE_BY_DESIGN = frozenset({"__slots__", "_register"})

BASELINE = {
    "max_scc": 1,
    "cyclic_edges": 0,
    "scc_without_base": 1,
    "recordset_max_scc": 1,
    "recordset_cyclic_edges": 0,
    "recordset_scc_without_base": 1,
    "unowned_shared_state": 4,
}


FIELD_BASELINE = {
    "max_scc": 1,
    "cyclic_edges": 0,
    "scc_without_base": 1,
    "unowned_shared_state": 1,
}


REGISTRY_BASELINE = {
    "max_scc": 1,
    "cyclic_edges": 0,
    "scc_without_base": 1,
    "unowned_shared_state": 0,
}


@dataclass(frozen=True)
class Composition:
    label: str
    root_dir: Path
    root_file: str
    unit_dir: Path
    stub_base: str
    root_class: str
    excluded: frozenset[str]
    baseline: dict[str, int]
    recordset_aware: bool


RECORDSET_PRODUCERS = frozenset(
    {
        "browse",
        "concat",
        "create",
        "exists",
        "filtered",
        "filtered_domain",
        "new",
        "search",
        "sorted",
        "sudo",
        "union",
        "with_company",
        "with_context",
        "with_env",
        "with_prefetch",
        "with_user",
        "_origin",
        "_spawn",
    }
)

NON_RECORDSET_ATTRS = frozenset(
    {
        "append",
        "clear",
        "copy",
        "count",
        "extend",
        "get",
        "index",
        "insert",
        "items",
        "keys",
        "pop",
        "remove",
        "setdefault",
        "sort",
        "update",
        "values",
    }
)


MODEL_COMPOSITION = Composition(
    label="BaseModel",
    root_dir=MODELS,
    root_file=BASE_UNIT,
    unit_dir=MIXINS,
    stub_base="_ModelStubs",
    root_class="BaseModel",
    excluded=EXCLUDED_UNITS,
    baseline=BASELINE,
    recordset_aware=True,
)

FIELD_COMPOSITION = Composition(
    label="Field",
    root_dir=ROOT / "odoo" / "orm" / "fields",
    root_file=BASE_UNIT,
    unit_dir=ROOT / "odoo" / "orm" / "fields",
    stub_base="_FieldStubs",
    root_class="Field",
    excluded=frozenset({"_field_stubs", "__init__"}),
    baseline=FIELD_BASELINE,
    recordset_aware=False,
)

REGISTRY_COMPOSITION = Composition(
    label="Registry",
    root_dir=ROOT / "odoo" / "orm" / "runtime",
    root_file="registry.py",
    unit_dir=ROOT / "odoo" / "orm" / "runtime",
    stub_base="_RegistryStubs",
    root_class="Registry",
    excluded=frozenset({"_registry_stubs", "__init__"}),
    baseline=REGISTRY_BASELINE,
    recordset_aware=False,
)

REQUEST_BASELINE = {
    "max_scc": 1,
    "cyclic_edges": 0,
    "scc_without_base": 1,
    "unowned_shared_state": 8,
}

CURSOR_BASELINE = {
    "max_scc": 1,
    "cyclic_edges": 0,
    "scc_without_base": 1,
    "unowned_shared_state": 5,
}

REQUEST_COMPOSITION = Composition(
    label="Request",
    root_dir=ROOT / "odoo" / "http",
    root_file="request_class.py",
    unit_dir=ROOT / "odoo" / "http",
    stub_base="RequestState",
    root_class="Request",
    excluded=frozenset({"__init__"}),
    baseline=REQUEST_BASELINE,
    recordset_aware=False,
)

CURSOR_COMPOSITION = Composition(
    label="Cursor",
    root_dir=ROOT / "odoo" / "db",
    root_file="cursor.py",
    unit_dir=ROOT / "odoo" / "db",
    stub_base="BaseCursor",
    root_class="Cursor",
    excluded=frozenset({"__init__"}),
    baseline=CURSOR_BASELINE,
    recordset_aware=False,
)

COMPOSITIONS = (
    MODEL_COMPOSITION,
    FIELD_COMPOSITION,
    REGISTRY_COMPOSITION,
    REQUEST_COMPOSITION,
    CURSOR_COMPOSITION,
)


@dataclass
class Unit:
    name: str
    files: list[str] = field(default_factory=list)
    defines: set[str] = field(default_factory=set)
    uses: set[str] = field(default_factory=set)
    recordset_uses: set[str] = field(default_factory=set)


def _is_composed_class(node: ast.ClassDef, comp: Composition) -> bool:

    if node.name == comp.root_class:
        return True
    if any(
        isinstance(b, ast.Name) and (b.id == comp.stub_base or b.id.endswith("Mixin"))
        for b in node.bases
    ):
        return True
    return node.name.endswith("Mixin")


def _bound_names(body: list[ast.stmt]):

    for stmt in body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield stmt.name
        elif isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if isinstance(target, ast.Name):
                    yield target.id
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            yield stmt.target.id
        elif isinstance(stmt, ast.If):
            yield from _bound_names(stmt.body)
            yield from _bound_names(stmt.orelse)


def _is_same_model_recordset(node: ast.expr) -> bool:

    if isinstance(node, ast.Name) and node.id == "self":
        return True
    if isinstance(node, ast.Subscript):
        return _is_same_model_recordset(node.value)
    if isinstance(node, ast.Call):
        func = node.func
        return (
            isinstance(func, ast.Attribute)
            and func.attr in RECORDSET_PRODUCERS
            and _is_same_model_recordset(func.value)
        )
    return False


class _SelfUseCollector(ast.NodeVisitor):
    def __init__(self, unit: Unit, comp: Composition | None = None) -> None:
        self.unit = unit
        self.comp = comp if comp is not None else MODEL_COMPOSITION
        self._nesting = 0
        self._recordset_locals: set[str] = set()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        composed = _is_composed_class(node, self.comp)
        if composed:
            self.unit.defines.update(_bound_names(node.body))
            self._nesting += 1
        self.generic_visit(node)
        if composed:
            self._nesting -= 1

    def _track(self, target: ast.expr, value: ast.expr) -> None:
        if isinstance(target, ast.Name) and _is_same_model_recordset(value):
            self._recordset_locals.add(target.id)

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            self._track(target, node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self._track(node.target, node.value)
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        if isinstance(node.target, ast.Name) and (
            _is_same_model_recordset(node.iter)
            or (
                isinstance(node.iter, ast.Name)
                and node.iter.id in self._recordset_locals
            )
        ):
            self._recordset_locals.add(node.target.id)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if self._nesting and isinstance(node.value, ast.Name):
            base = node.value.id
            if base in ("self", "cls"):
                self.unit.uses.add(node.attr)
                self.unit.recordset_uses.add(node.attr)
            elif (
                base in self._recordset_locals and node.attr not in NON_RECORDSET_ATTRS
            ):
                self.unit.recordset_uses.add(node.attr)
        self.generic_visit(node)


def _unit_name(path: Path, comp: Composition) -> str:

    if path.name == comp.root_file and path.parent == comp.root_dir:
        return comp.root_file
    if path.parent != comp.unit_dir:
        return f"{path.parent.name}/{path.stem}"
    return path.stem


def collect_units(comp: Composition = None) -> dict[str, Unit]:
    comp = comp if comp is not None else MODEL_COMPOSITION
    units: dict[str, Unit] = {}
    paths = [
        p
        for p in comp.unit_dir.rglob("*.py")
        if "__pycache__" not in p.parts and "tests" not in p.parts
    ]
    root = comp.root_dir / comp.root_file
    if root not in paths:
        paths.append(root)
    for path in sorted(paths):
        name = _unit_name(path, comp)
        if name in comp.excluded:
            continue
        unit = units.setdefault(name, Unit(name))
        unit.files.append(path.name)
        _SelfUseCollector(unit, comp).visit(
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        )
    return {n: u for n, u in units.items() if u.defines or u.uses}


def build_edges(
    units: dict[str, Unit], *, through_recordsets: bool = False
) -> tuple[dict[str, dict[str, set[str]]], dict]:

    owner: dict[str, str] = {}
    collisions: dict[str, set[str]] = defaultdict(set)
    for name in sorted(units):
        for member in sorted(units[name].defines):
            if member in owner and member not in DUPLICATE_BY_DESIGN:
                collisions[member].update({owner[member], name})
            else:
                owner.setdefault(member, name)

    edges: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for name, unit in units.items():
        members = unit.recordset_uses if through_recordsets else unit.uses
        for member in members:
            target = owner.get(member)
            if target is not None and target != name:
                edges[name][target].add(member)
    return edges, dict(collisions)


def strongly_connected(
    nodes: set[str], edges: dict[str, dict[str, set[str]]]
) -> list[list[str]]:
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    result: list[list[str]] = []
    counter = 0

    for root in sorted(nodes):
        if root in index:
            continue
        work: list[tuple[str, list[str]]] = [(root, sorted(edges.get(root, ())))]
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack.add(root)
        while work:
            node, pending = work[-1]
            progressed = False
            while pending:
                nxt = pending.pop(0)
                if nxt not in nodes:
                    continue
                if nxt not in index:
                    index[nxt] = low[nxt] = counter
                    counter += 1
                    stack.append(nxt)
                    on_stack.add(nxt)
                    work.append((nxt, sorted(edges.get(nxt, ()))))
                    progressed = True
                    break
                if nxt in on_stack:
                    low[node] = min(low[node], index[nxt])
            if progressed:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index[node]:
                component = []
                while True:
                    top = stack.pop()
                    on_stack.discard(top)
                    component.append(top)
                    if top == node:
                        break
                result.append(sorted(component))
    return result


def measure(
    *, through_recordsets: bool = False, comp: Composition | None = None
) -> dict:
    comp = comp if comp is not None else MODEL_COMPOSITION
    units = collect_units(comp)
    edges, collisions = build_edges(units, through_recordsets=through_recordsets)
    names = set(units)

    sccs = [c for c in strongly_connected(names, edges) if len(c) > 1]
    without_base = [
        c for c in strongly_connected(names - {comp.root_file}, edges) if len(c) > 1
    ]

    component_of: dict[str, int] = {}
    for i, component in enumerate(sccs):
        for unit in component:
            component_of[unit] = i
    cyclic = sum(
        1
        for src, targets in edges.items()
        for dst in targets
        if component_of.get(src, -1) == component_of.get(dst, -2)
    )

    return {
        "units": sorted(names),
        "edges_total": sum(len(t) for t in edges.values()),
        "cyclic_edges": cyclic,
        "max_scc": max((len(c) for c in sccs), default=1),
        "sccs": sorted(sccs, key=len, reverse=True),
        "scc_without_base": max((len(c) for c in without_base), default=1),
        "sccs_without_base": sorted(without_base, key=len, reverse=True),
        "collisions": {k: sorted(v) for k, v in collisions.items()},
        "unowned_shared_state": len(unowned_shared_state(comp)),
        "_unowned_shared_state": unowned_shared_state(comp),
        "_edges": edges,
        "_units": units,
    }


def unowned_shared_state(comp: Composition) -> dict[str, list[str]]:

    return unowned_from_units(collect_units(comp))


def unowned_from_units(units: dict[str, Unit]) -> dict[str, list[str]]:

    owner: dict[str, str] = {}
    for name in sorted(units):
        for member in sorted(units[name].defines):
            owner.setdefault(member, name)
    readers: dict[str, set[str]] = defaultdict(set)
    for name, unit in units.items():
        for member in unit.uses:
            if member.startswith("__") or member in owner:
                continue
            readers[member].add(name)
    return {m: sorted(r) for m, r in sorted(readers.items()) if len(r) > 1}


def _verdicts(
    m: dict, wide: dict | None = None, baseline: dict | None = None
) -> list[tuple[str, int, int, str]]:

    pairs = [
        ("max_scc", m["max_scc"]),
        ("cyclic_edges", m["cyclic_edges"]),
        ("scc_without_base", m["scc_without_base"]),
    ]
    if "unowned_shared_state" in (baseline or {}):
        pairs.append(("unowned_shared_state", m["unowned_shared_state"]))
    if wide is not None:
        pairs += [
            ("recordset_max_scc", wide["max_scc"]),
            ("recordset_cyclic_edges", wide["cyclic_edges"]),
            ("recordset_scc_without_base", wide["scc_without_base"]),
        ]
    floors = baseline if baseline is not None else BASELINE
    out = []
    for key, actual in pairs:
        floor = floors[key]
        if actual > floor:
            status = "GREW"
        elif actual < floor:
            status = "IMPROVED"
        else:
            status = "ok"
        out.append((key, actual, floor, status))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="CI mode: exit 1 on any drift"
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument(
        "--explain",
        nargs=2,
        metavar=("FROM", "TO"),
        help="list the members that create one edge",
    )
    parser.add_argument(
        "--composition",
        choices=[c.label for c in COMPOSITIONS],
        default=MODEL_COMPOSITION.label,
        help="which composition --explain refers to (default: BaseModel)",
    )
    args = parser.parse_args(argv)

    chosen = next(c for c in COMPOSITIONS if c.label == args.composition)
    m = measure(comp=chosen)

    if args.explain:
        src, dst = args.explain
        direct = m["_edges"].get(src, {}).get(dst) or set()
        wide_edges = (
            measure(through_recordsets=True, comp=chosen)["_edges"]
            if chosen.recordset_aware
            else m["_edges"]
        )
        wide = wide_edges.get(src, {}).get(dst) or set()
        if not direct and not wide:
            print(f"no edge {src} -> {dst}", file=sys.stderr)
            return 2
        if direct:
            print(f"{src} -> {dst} via {len(direct)} member(s) on self:")
            for member in sorted(direct):
                print(f"  {member}")
        if indirect := wide - direct:
            print(
                f"{src} -> {dst} via {len(indirect)} member(s) reached through "
                f"another recordset of the same model:"
            )
            for member in sorted(indirect):
                print(f"  {member}")
        return 0

    reports = []
    for comp in COMPOSITIONS:
        cm = m if comp is chosen else measure(comp=comp)
        cwide = (
            measure(through_recordsets=True, comp=comp)
            if comp.recordset_aware
            else None
        )
        reports.append((comp, cm, cwide, _verdicts(cm, cwide, comp.baseline)))

    if args.json:
        print(
            json.dumps(
                {
                    comp.label: {
                        "metrics": {k: a for k, a, _, _ in vs},
                        "baseline": comp.baseline,
                        "status": {k: st for k, _, _, st in vs},
                        "sccs": cm["sccs"],
                        "recordset_sccs": cwide["sccs"] if cwide else None,
                        "collisions": cm["collisions"],
                    }
                    for comp, cm, cwide, vs in reports
                },
                indent=2,
            )
        )
    else:
        for comp, cm, cwide, vs in reports:
            print(f"{comp.label} mixin coupling check")
            print("=" * 64)
            for key, actual, floor, status in vs:
                flag = "ok" if status == "ok" else status
                print(f"[{flag:>8}] {key}: {actual} (baseline {floor})")
            print("-" * 64)
            print(f"units: {len(cm['units'])}   inter-unit edges: {cm['edges_total']}")
            for component in cm["sccs"]:
                print(f"  cycle of {len(component)}: {', '.join(component)}")
            if cwide is not None:
                print(
                    f"through recordsets: {cwide['edges_total']} edges, "
                    f"{cwide['cyclic_edges']} cyclic"
                )
                for component in cwide["sccs"]:
                    print(
                        f"  cycle of {len(component)} via recordsets: "
                        f"{', '.join(component)}"
                    )
            if cm["scc_without_base"] < cm["max_scc"]:
                print(
                    f"  without {comp.root_file}: largest cycle is "
                    f"{cm['scc_without_base']} — the rest of the cycle is "
                    f"{comp.root_file} being both composition root and "
                    f"metadata holder"
                )
            for component in cm["sccs_without_base"]:
                print(f"    residual cycle: {', '.join(component)}")
            if cm["collisions"]:
                print("\nname defined by more than one unit (MRO order decides):")
                for name, owners in sorted(cm["collisions"].items()):
                    print(f"  {name}: {', '.join(owners)}")
            else:
                print("\nNo cross-unit name collisions. ✓")
            print()

    verdicts = [(comp.label, *v) for comp, _, _, vs in reports for v in vs]

    grew = [v for v in verdicts if v[4] == "GREW"]
    improved = [v for v in verdicts if v[4] == "IMPROVED"]

    if args.check:
        if grew:
            print("\nFAILED: mixin coupling grew:", file=sys.stderr)
            for label, key, actual, floor, _ in grew:
                print(f"  {label}.{key}: {floor} -> {actual}", file=sys.stderr)
            return 1
        if improved:
            print(
                "\nFAILED: coupling improved but the baseline was not lowered "
                "(exact-mode ratchet — commit the new floor):",
                file=sys.stderr,
            )
            for label, key, actual, floor, _ in improved:
                print(f"  {label}.{key}: {floor} -> {actual}", file=sys.stderr)
            return 1
        print(
            f"Mixin coupling within baseline, all {len(COMPOSITIONS)} compositions. ✓"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

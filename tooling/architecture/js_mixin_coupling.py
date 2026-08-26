from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import doc_measured
from _repo_root import find_odoo_root

ADR = "0024"

ROOT = find_odoo_root(Path(__file__).resolve(), tool="js_mixin_coupling")
WEB_SRC = ROOT / "addons" / "web" / "static" / "src"
ANALYZER = Path(__file__).with_suffix(".mjs")

COMPOSITIONS = {
    "search/search_model.js": [
        "search/search_query_mixin.js",
        "search/search_split_domain_mixin.js",
        "search/search_favorites_mixin.js",
        "search/search_properties_mixin.js",
        "search/search_panel/search_panel_mixin.js",
    ],
    "views/list/list_renderer.js": [
        "views/list/list_styling.js",
        "views/list/list_group_rendering.js",
        "views/list/list_sorting.js",
    ],
}

BASELINE = {
    "max_scc": 6,
    "cyclic_edges": 19,
    "foreign": 208,
    "shared_privates": 4,
}


@dataclass
class Unit:
    module: str
    defines: set[str] = field(default_factory=set)
    uses: set[str] = field(default_factory=set)
    dynamic: int = 0

    @property
    def foreign(self) -> set[str]:
        return self.uses - self.defines


def modules() -> list[str]:
    out = []
    for base, mixins in COMPOSITIONS.items():
        out.append(base)
        out.extend(mixins)
    return sorted(set(out))


def analyse(mods: list[str]) -> dict[str, Unit]:
    paths = [WEB_SRC / m for m in mods]
    missing = [p for p in paths if not p.is_file()]
    if missing:
        raise SystemExit(
            "js_mixin_coupling: declared module(s) not on disk -- update "
            "COMPOSITIONS:\n  " + "\n  ".join(str(p) for p in missing)
        )
    proc = subprocess.run(
        ["node", str(ANALYZER), *[str(p) for p in paths]],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"mixin analyzer failed: {proc.stderr.strip()}")
    units = {}
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        rel = Path(raw["file"]).resolve().relative_to(WEB_SRC.resolve()).as_posix()
        units[rel] = Unit(
            module=rel,
            defines=set(raw["defines"]),
            uses=set(raw["uses"]),
            dynamic=raw["dynamic"],
        )
    return units


def _groups(units: dict[str, Unit], compositions=None) -> list[list[Unit]]:

    compositions = COMPOSITIONS if compositions is None else compositions
    groups, grouped = [], set()
    for base, mixins in compositions.items():
        members = [units[m] for m in (base, *mixins) if m in units]
        if members:
            groups.append(members)
            grouped.update(u.module for u in members)
    if ungrouped := [u for m, u in units.items() if m not in grouped]:
        groups.append(ungrouped)
    return groups


def build_edges(units: dict[str, Unit], compositions=None) -> set[tuple[str, str]]:

    edges = set()
    for group in _groups(units, compositions):
        for a in group:
            for b in group:
                if a.module == b.module:
                    continue
                if a.foreign & b.defines:
                    edges.add((a.module, b.module))
    return edges


def strongly_connected(
    nodes: list[str], edges: set[tuple[str, str]]
) -> list[list[str]]:
    succ: dict[str, list[str]] = {n: [] for n in nodes}
    for a, b in edges:
        succ[a].append(b)
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    result: list[list[str]] = []
    counter = 0

    for root in nodes:
        if root in index:
            continue
        work = [(root, iter(sorted(succ[root])))]
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack.add(root)
        while work:
            node, children = work[-1]
            advanced = False
            for child in children:
                if child not in index:
                    index[child] = low[child] = counter
                    counter += 1
                    stack.append(child)
                    on_stack.add(child)
                    work.append((child, iter(sorted(succ[child]))))
                    advanced = True
                    break
                if child in on_stack:
                    low[node] = min(low[node], index[child])
            if advanced:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index[node]:
                component = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.append(member)
                    if member == node:
                        break
                result.append(sorted(component))
    return result


def cyclic_edges(
    edges: set[tuple[str, str]], components: list[list[str]]
) -> set[tuple[str, str]]:
    owner = {n: i for i, c in enumerate(components) for n in c}
    sizes = {i: len(c) for i, c in enumerate(components)}
    return {
        (a, b)
        for a, b in edges
        if owner.get(a) == owner.get(b) and sizes.get(owner.get(a), 0) > 1
    }


def shared_privates(units: dict[str, Unit], compositions=None) -> dict[str, list[str]]:

    users: dict[str, list[str]] = {}
    for group in _groups(units, compositions):
        defined_by = {
            name: u.module for u in group for name in u.defines if name.startswith("_")
        }
        in_group: dict[str, list[str]] = {}
        for unit in group:
            for name in unit.foreign:
                if name in defined_by and defined_by[name] != unit.module:
                    in_group.setdefault(name, []).append(unit.module)
        for name, mods in in_group.items():
            if len(mods) >= 2:
                users.setdefault(name, []).extend(mods)
    return {n: sorted(m) for n, m in sorted(users.items())}


def measure() -> dict:
    units = analyse(modules())
    nodes = sorted(units)
    edges = build_edges(units)
    components = strongly_connected(nodes, edges)
    cyc = cyclic_edges(edges, components)
    shared = shared_privates(units)
    return {
        "units": units,
        "nodes": nodes,
        "edges": edges,
        "components": components,
        "cyclic": cyc,
        "shared": shared,
        "metrics": {
            "max_scc": max((len(c) for c in components), default=0),
            "cyclic_edges": len(cyc),
            "foreign": sum(len(u.foreign) for u in units.values()),
            "shared_privates": len(shared),
        },
    }


def doc_metrics(state: dict) -> dict[str, int]:
    m = state["metrics"]
    return {
        "units": len(state["nodes"]),
        "edges": len(state["edges"]),
        "max_scc": m["max_scc"],
        "cyclic_edges": m["cyclic_edges"],
        "foreign": m["foreign"],
        "shared_privates": m["shared_privates"],
        "dynamic": sum(u.dynamic for u in state["units"].values()),
    }


def report(state: dict) -> str:
    units, metrics = state["units"], state["metrics"]
    out = ["JS mixin-coupling graph (drift-zero)", "=" * 72, ""]
    out.append(f"{'unit':<46}{'defines':>9}{'uses':>7}{'foreign':>9}")
    for mod in state["nodes"]:
        u = units[mod]
        out.append(f"  {mod:<44}{len(u.defines):>9}{len(u.uses):>7}{len(u.foreign):>9}")
    out.append("")
    for name, users in state["shared"].items():
        out.append(f"  this.{name} — reached by {len(users)} unit(s)")
    out.append("")
    for key, value in sorted(metrics.items()):
        floor = BASELINE[key]
        mark = "ok" if value == floor else ("DOWN" if value < floor else "UP")
        out.append(f"  [{mark:>4}] {key:<16} {value:>4}   baseline {floor}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="gate against BASELINE")
    parser.add_argument("--json", action="store_true")
    doc_measured.main_flags(parser)
    args = parser.parse_args(argv)

    if not modules():
        parser.error("COMPOSITIONS is empty — the gate would scan nothing")

    state = measure()

    if args.update_doc or args.check_doc:
        metrics = doc_metrics(state)
        path = Path(__file__)
        if args.update_doc:
            changed = doc_measured.update(path, metrics)
            print(
                f"{'updated' if changed else 'already fresh'}: {doc_measured.render(metrics)}"
            )
            return 0
        problems = doc_measured.check(path, metrics)
        if problems:
            print("module docstring's MEASURED block is stale:")
            for problem in problems:
                print(f"  {problem}")
            return 1
        print(f"[ ok] MEASURED block is fresh: {doc_measured.render(metrics)}")
        return 0

    if args.json:
        print(
            json.dumps(
                {
                    "metrics": state["metrics"],
                    "baseline": BASELINE,
                    "units": {
                        m: {
                            "defines": sorted(u.defines),
                            "uses": sorted(u.uses),
                            "foreign": sorted(u.foreign),
                            "dynamic": u.dynamic,
                        }
                        for m, u in state["units"].items()
                    },
                    "edges": sorted(state["edges"]),
                    "components": state["components"],
                    "shared_privates": state["shared"],
                },
                indent=2,
            )
        )
        return 0

    print(report(state))

    if not args.check:
        return 0

    drift = {
        k: (v, BASELINE[k]) for k, v in state["metrics"].items() if v != BASELINE[k]
    }
    if not drift:
        print("\nNo mixin-coupling drift. ✓")
        return 0
    print("\nMixin-coupling drift:")
    for key, (value, floor) in sorted(drift.items()):
        direction = "grew" if value > floor else "improved"
        print(f"  {key}: {floor} -> {value} ({direction})")
    print(
        "\n  An improvement must be locked in: update BASELINE in this file and\n"
        "  regenerate the MEASURED block (--update-doc) in the same commit."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

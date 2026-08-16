import argparse
import json
import posixpath
import sys
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from js_imports import collect_imports
from js_layer_check import ROOT

ADR = "0019"

ADDON_ROOTS: tuple[Path, ...] = (ROOT / "addons", ROOT / "odoo" / "addons")

EXCLUDED_PARTS = frozenset({"lib", "legacy", "__pycache__"})


@dataclass(frozen=True)
class KnownCycle:
    modules: frozenset[str]
    reason: str


KNOWN_CYCLES: tuple[KnownCycle, ...] = (
    KnownCycle(
        modules=frozenset(
            {
                "point_of_sale/app/utils/order_change_receipts",
                "point_of_sale/app/services/pos_store",
            }
        ),
        reason=(
            "`order_change_receipts` imports the `CONSOLE_COLOR` constant from "
            "`pos_store`, which imports six receipt helpers back. Safe under "
            "every entry order: all seven cycle-internal bindings were "
            "enumerated and every reference sits inside a function or method "
            "body — `CONSOLE_COLOR` in a `catch` inside `getStrNotes`, and the "
            "six helpers only in the `PosStore` methods that delegate to them "
            "(`pos_store.js:2326-2411`). Tolerated, not endorsed: moving "
            "`CONSOLE_COLOR` to a leaf module removes the cycle outright."
        ),
    ),
)


@dataclass
class Cycle:
    modules: list[str]
    edges: list[tuple[str, str]]


@cache
def addon_src_dirs() -> dict[str, Path]:

    dirs: dict[str, Path] = {}
    for root in ADDON_ROOTS:
        if not root.is_dir():
            continue
        for addon in sorted(root.iterdir()):
            src = addon / "static" / "src"
            if src.is_dir() and addon.name not in dirs:
                dirs[addon.name] = src
    return dirs


def iter_source_files() -> list[tuple[str, Path]]:
    out: list[tuple[str, Path]] = []
    for addon, src in addon_src_dirs().items():
        for path in sorted(src.rglob("*.js")):
            rel_parts = path.relative_to(src).parts
            if EXCLUDED_PARTS.intersection(rel_parts):
                continue
            out.append((f"{addon}/{path.relative_to(src).as_posix()[:-3]}", path))
    return out


def _resolve(spec: str, importer_id: str) -> str | None:

    addon = importer_id.split("/", 1)[0]
    if spec.startswith("."):
        rel = posixpath.normpath(
            posixpath.join(posixpath.dirname(importer_id.split("/", 1)[1]), spec)
        )
        if rel.startswith(".."):
            return None
    elif spec.startswith("@"):
        addon, _, rel = spec[1:].partition("/")
        if not rel or rel.startswith("../"):
            return None
    else:
        return None
    rel = rel.removesuffix(".js")
    src = addon_src_dirs().get(addon)
    if src is None or not (src / f"{rel}.js").is_file():
        return None
    return f"{addon}/{rel}"


def build_graph(
    files: list[tuple[str, Path]] | None = None,
) -> dict[str, list[str]]:

    graph: dict[str, list[str]] = {}
    for module_id, path in files if files is not None else iter_source_files():
        try:
            src = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as exc:  # pragma: no cover
            print(f"warning: could not read {path}: {exc}", file=sys.stderr)
            graph[module_id] = []
            continue
        deps: list[str] = []
        for spec, _lineno in collect_imports(src):
            target = _resolve(spec, module_id)
            if target is not None and target != module_id and target not in deps:
                deps.append(target)
        graph[module_id] = deps
    return graph


def find_cycles(graph: dict[str, list[str]]) -> list[Cycle]:

    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    counter = 0
    cycles: list[Cycle] = []

    for root in graph:
        if root in index:
            continue
        work: list[tuple[str, int]] = [(root, 0)]
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack.add(root)
        while work:
            node, i = work[-1]
            deps = graph.get(node, ())
            if i < len(deps):
                work[-1] = (node, i + 1)
                dep = deps[i]
                if dep not in graph:
                    continue
                if dep not in index:
                    index[dep] = low[dep] = counter
                    counter += 1
                    stack.append(dep)
                    on_stack.add(dep)
                    work.append((dep, 0))
                elif dep in on_stack:
                    low[node] = min(low[node], index[dep])
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index[node]:
                component: list[str] = []
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    component.append(w)
                    if w == node:
                        break
                is_self_loop = len(component) == 1 and component[0] in graph.get(
                    component[0], ()
                )
                if len(component) > 1 or is_self_loop:
                    members = set(component)
                    edges = sorted(
                        (m, d)
                        for m in component
                        for d in graph.get(m, ())
                        if d in members
                    )
                    cycles.append(Cycle(modules=sorted(component), edges=edges))
    return cycles


def check(
    files: list[tuple[str, Path]] | None = None,
) -> tuple[list[Cycle], list[Cycle]]:
    known_sets = {k.modules for k in KNOWN_CYCLES}
    new: list[Cycle] = []
    known: list[Cycle] = []
    for cycle in sorted(find_cycles(build_graph(files)), key=lambda c: c.modules):
        (known if frozenset(cycle.modules) in known_sets else new).append(cycle)
    return new, known


def _fmt(module: str) -> str:
    return f"@{module}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="CI mode: exit 1 on any NEW cycle"
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    files = iter_source_files()
    scanned = len(files)
    if not scanned:
        parser.error("no JS sources found — the scan reached nothing")

    new, known = check(files)

    if args.json:
        print(
            json.dumps(
                {
                    "new": [
                        {"modules": c.modules, "edges": [list(e) for e in c.edges]}
                        for c in new
                    ],
                    "known": [{"modules": c.modules} for c in known],
                    "files_scanned": scanned,
                },
                indent=2,
            )
        )
    else:
        print("JS import-cycle check (drift-zero)")
        print("=" * 64)
        if new:
            print(f"\n{len(new)} NEW cycle(s) — these fail the gate:\n")
            for c in new:
                print(f"  strongly-connected component of {len(c.modules)} module(s):")
                for m in c.modules:
                    print(f"      {_fmt(m)}")
                print("    edges inside the cycle:")
                for a, b in c.edges:
                    print(f"      {_fmt(a)}  ->  {_fmt(b)}")
                print(
                    "    A cycle is safe only while the bundle keeps evaluating it\n"
                    "    from the right side. If any module in it reads an imported\n"
                    "    binding at module-evaluation time, native ESM throws and an\n"
                    "    esbuild bundle silently substitutes `undefined`. Break the\n"
                    "    cycle, or pin it in KNOWN_CYCLES with a reason.\n"
                )
        else:
            print("\nNo new import cycles. ✓")
        if known:
            print(f"\n{len(known)} known cycle(s) tolerated (tracked debt):\n")
            for c in known:
                print(f"  {' <-> '.join(_fmt(m) for m in c.modules)}")
        print(f"\nFiles scanned: {scanned}")
        print(f"New: {len(new)}   Known/tolerated: {len(known)}")

    if args.check and new:
        print(f"\nFAILED: {len(new)} new JS import cycle(s).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Drift-zero import-cycle gate for every addon's JavaScript in this repo.

``js_layer_check.py`` locks import *direction*. It cannot see import *cycles*:
every edge of a cycle can sit inside one layer and break no contract. Nothing
else in the toolchain looks either — ESLint has no cycle rule enabled, and a
cycle is invisible to the typechecker and to the test suite, because whether a
cycle hurts depends on which module the bundle happens to evaluate first.

Why that matters here, concretely. ``core/py_js`` carried a six-module cycle
(``py_date -> py_args -> py_builtin -> py_date``) while ``py_builtin`` read the
date classes *while evaluating its own body*. The outcome depended entirely on
the entry order:

  * entered at ``py.js``/``py_builtin``/``py_compare`` -> correct;
  * entered at ``py_date``/``py_timedelta``/``py_utils``:
      - native ESM (debug, per-file ``<script type=module>``):
        ``ReferenceError: Cannot access 'PyDate' before initialization``;
      - ``esbuild --bundle`` (production): **no error at all** — the initializer
        is hoisted, the table is built with ``undefined`` keys, and every
        Python type name silently degrades from ``'date'`` to ``'PyDate'``.

The shipped order happened to be the safe one, so the whole thing was invisible
to 1904 passing tests. A gate on the *structure* is the only thing that catches
this before the ordering changes; a gate on behaviour cannot.

The rule is therefore blunt on purpose: **no cycles**, with pre-existing ones
pinned in ``KNOWN_CYCLES`` as visible debt — the same drift-zero contract, and
the same escape hatch, as ``js_layer_check.KNOWN_VIOLATIONS``. A cycle that is
harmless today is still a latent ordering dependency tomorrow; pinning it makes
that a decision someone took rather than one nobody noticed.

Usage::

    python tooling/architecture/js_cycle_check.py            # human-readable report
    python tooling/architecture/js_cycle_check.py --check    # CI mode, exit 1 on any new cycle
    python tooling/architecture/js_cycle_check.py --json     # machine-readable

Type-only imports do not count: ``collect_imports`` is reused from
``js_layer_check``, so JSDoc ``@import`` tags and ``import("...")`` inside
comments create no edge here either.
"""

import argparse
import json
import posixpath
import sys
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from js_layer_check import ROOT, collect_imports

# Every addon's client source in this repo, not just ``web``'s: a cycle in
# ``mail`` or ``point_of_sale`` fails exactly the same way, and the
# named-export gate already scans this same wide surface for the same reason.
# Sibling checkouts are absent from a CI
# checkout, so they are covered by the pre-push hook rather than here.
ADDON_ROOTS: tuple[Path, ...] = (ROOT / "addons", ROOT / "odoo" / "addons")

# Vendored third-party bundles and pre-layering code are not governed.
EXCLUDED_PARTS = frozenset({"lib", "legacy", "__pycache__"})


@dataclass(frozen=True)
class KnownCycle:
    """A pre-existing, tolerated cycle, pinned with its rationale.

    ``modules`` is the complete set of module ids in the strongly-connected
    component (``<addon>/<path>``, no ``.js``). The set must match exactly:
    growing a known cycle by one module fails the gate, because that is a new
    structure nobody signed off on.
    """

    modules: frozenset[str]
    reason: str


KNOWN_CYCLES: tuple[KnownCycle, ...] = (
    KnownCycle(
        modules=frozenset(
            {"web/views/list/list_keyboard_nav", "web/views/list/list_keyboard_edit"}
        ),
        reason=(
            "Mutual recursion between two halves of one deliberately split "
            "module: `nav` calls `makeEditHandlers`, `edit` calls "
            "`getElementToFocus`. Both references are inside function bodies, "
            "so neither module reads the other while its own body evaluates "
            "and no entry order can break it. Tolerated, not endorsed: merging "
            "the pair or extracting the shared helper would remove it."
        ),
    ),
    KnownCycle(
        modules=frozenset(
            {
                "mail/core/common/_models",
                "mail/core/common/store_service",
                "mail/core/common/res_partner_model",
                "mail/core/common/mail_guest_model",
            }
        ),
        reason=(
            "Barrel-induced: `store_service` imports `_models` for its side "
            "effects, `_models` pulls in every record model, and two of those "
            "models import `Store` back. Safe under every entry order, and the "
            "argument is exhaustive rather than a spot check: `_models` has no "
            "named imports at all and `store_service` takes no binding from the "
            "component, so `Store` is the ONLY cycle-internal binding. It "
            "occurs exactly twice — `res_partner_model.js:16` and "
            "`mail_guest_model.js:28` — both inside `static new()`, a method "
            "body evaluated when a record is built, never while the module "
            "evaluates. Re-run that grep before adding a fifth module here."
        ),
    ),
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
    """Addon technical name -> its ``static/src`` directory.

    An addon present under both roots resolves to the first root that has it,
    which is the same precedence the ``addons_path`` gives.
    """
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
    """``[(module_id, path), ...]`` for every governed client-source file."""
    out: list[tuple[str, Path]] = []
    for addon, src in addon_src_dirs().items():
        for path in sorted(src.rglob("*.js")):
            rel_parts = path.relative_to(src).parts
            if EXCLUDED_PARTS.intersection(rel_parts):
                continue
            out.append((f"{addon}/{path.relative_to(src).as_posix()[:-3]}", path))
    return out


def _resolve(spec: str, importer_id: str) -> str | None:
    """Resolve an import specifier to a first-party module id.

    Returns ``None`` for anything that is not an addon's ``static/src`` module
    (``@odoo/owl``, ``@web/../lib/...``, a bare package, a missing file).
    """
    addon = importer_id.split("/", 1)[0]
    if spec.startswith("."):
        # ``posixpath``, not ``Path.resolve``: this is pure specifier
        # arithmetic on forward-slash module ids, with no filesystem or
        # symlink semantics wanted. A relative specifier never leaves its own
        # addon, so the addon prefix is carried through unchanged.
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
    """Module id -> ordered list of first-party module ids it imports.

    ``files`` lets a caller that already walked the tree pass the result in, so
    the reported "Files scanned" count describes the walk that was actually
    analysed rather than a second one taken moments later.
    """
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
    """Tarjan's strongly-connected components, iterative (the graph is ~700
    modules deep in places and CPython's recursion limit is not a contract).

    Returns every SCC with more than one module, plus any self-loop. The gate's
    own graph never contains one (`build_graph` filters it), but this function
    is also driven directly from tests with hand-built graphs.
    """
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    counter = 0
    cycles: list[Cycle] = []

    for root in graph:
        if root in index:
            continue
        # (node, iterator position) frames, walked explicitly.
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
                # `build_graph` drops any dep equal to the importing module, so
                # the gate's own pipeline never produces a self-edge. The check
                # is kept because `find_cycles` is called directly with
                # hand-built graphs (its self-import case is pinned in
                # `test_js_cycle_check`), and a detector that silently ignores
                # the degenerate cycle when handed one is worse than one that
                # never sees it.
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
    """Return ``(new_cycles, known_cycles)``."""
    known_sets = {k.modules for k in KNOWN_CYCLES}
    new: list[Cycle] = []
    known: list[Cycle] = []
    for cycle in sorted(find_cycles(build_graph(files)), key=lambda c: c.modules):
        (known if frozenset(cycle.modules) in known_sets else new).append(cycle)
    return new, known


def _fmt(module: str) -> str:
    """``mail/core/common/record`` -> ``@mail/core/common/record``."""
    return f"@{module}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="CI mode: exit 1 on any NEW cycle"
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    files = iter_source_files()
    new, known = check(files)
    scanned = len(files)

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

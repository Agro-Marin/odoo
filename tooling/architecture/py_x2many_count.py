#!/usr/bin/env python3
"""Counters that count by hand, which ADR-0052 replaced with ``fields.Count``.

Two shapes, both of which the record argues should stop being written:

* ``record.<counter> = len(record.<x2many>)`` inside a ``_compute*`` method --
  the WHOLE assignment, not a ``len()`` anywhere in one.
  It reads as the batched form and is the slowest of the three at list-view
  scale -- ``One2many.read`` does not count, it instantiates every line of every
  record in the prefetch set and groups them in Python -- while on a warm cache
  it is the fastest. ``fields.Count`` takes that branch per call.
* ``search_count()`` inside a ``for`` loop over ``self`` in a ``_compute*``
  method. One query per record, which ``test_lint E8507`` already counts as a
  query inside a loop; it is here too because the fix is usually the same
  declaration rather than a hand-written ``_read_group``.

THE ``_ids`` SUFFIX IS DOING REAL WORK HERE, and that is deliberate rather than
sloppy: ``coding_guidelines.rst``'s naming table fixes ``_ids`` for relational
fields, so a name ending that way is a relation by the fork's own rule. Resolving
the field properly would mean following ``_inherit`` across files to find where
it was declared, and a ratchet wants a definition that is stable and cheap to
re-derive over one that is complete. A counter over a field named otherwise is
missed, and that is the trade.

NOR A ``len()`` THAT IS NOT A COUNTER. ADR-0052 replaced a counter FIELD, and
`fields.Count` can express nothing else, so the `len()` has to be the entire
right-hand side of an assignment to a field on the record being looped over.
`len(move.suitable_journal_ids) > 1` is a boolean, `i == len(self.line_ids) - 1`
is an index bound, and `done = len(enrollment.completion_ids)` is a ratio
numerator bound to a local -- all legitimate, none convertible. Counting them
inflated the floor with code that has no fix, which is the same defect as the
guard below and was found the same way: by reading the sites instead of the
number.

NOR A ``len()`` UNDER A ``NewId`` GUARD. ``fields.Count`` itself falls back to
``len()`` for an unsaved record, because its lines are in cache and in no table;
a compute that already does the same thing by hand -- ``if not any(self._ids):``
and then ``len()``, ``_read_group`` otherwise -- is the correct shape, not the
one this gate exists to remove. Counting it would put correct code in the floor,
and a gate whose findings include correct code is read as broken and ignored.
Three sites in ``addons/project/models/project_task.py`` are exactly this.

WHAT IT DOES NOT COUNT. A ``len()`` over a multi-hop path
(``len(record.parent_id.line_ids)``) is not a field on the record, so
``fields.Count`` cannot express it and it is out of scope. Nor is a compute that
already uses ``_read_group``: those are correct as written and this gate must not
push anyone off them.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root, sibling_repos_root

ADR = "0052"

ROOT = find_odoo_root(Path(__file__).resolve(), tool="py_x2many_count")

SCOPE = ROOT / "odoo"

DEFAULT_ADDON = "core"

ALL_ADDONS = "addons"

#: Sibling checkouts, resolved beside the odoo one rather than under `addons/`.
#: They are absent from a single-repo CI run by construction -- no workflow in
#: `odoo` passes `repository:` to actions/checkout -- so asking for one there
#: SKIPS rather than reporting zero, which a count ratchet would read as a
#: catastrophic improvement and refuse. Their own `architecture.yml` builds the
#: two-checkout topology and runs this gate from the odoo side, exactly as
#: `js_face_boundary` and `js_public_surface` already do.
SIBLING_SCOPES = ("enterprise", "agromarin")

#: Scopes `--addon` accepts. A tree absent from here is measured by nothing --
#: the same rule as the other per-addon gates, and the same reason: a floor of
#: zero over an unscanned tree checks nothing while looking like it does.
GOVERNED_ADDONS = (
    DEFAULT_ADDON,
    ALL_ADDONS,
    "mail",
    "account",
    "stock",
    "project",
    *SIBLING_SCOPES,
)

RELATIONAL_SUFFIX = "_ids"


def addon_src(addon: str = DEFAULT_ADDON) -> Path:
    if addon == DEFAULT_ADDON:
        return SCOPE
    if addon == ALL_ADDONS:
        return ROOT / "addons"
    if addon in SIBLING_SCOPES:
        return sibling_repos_root(ROOT) / addon
    return ROOT / "addons" / addon


@dataclass(frozen=True)
class HandCount:
    file: str
    line: int
    kind: str
    what: str

    def __str__(self) -> str:
        return f"  {self.kind:12}  {self.file}:{self.line}  {self.what}"


def _display(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _is_test_path(path: Path) -> bool:
    return "tests" in path.parts or path.name.startswith("test_")


def iter_source_files(src: Path | None = None) -> list[Path]:
    return sorted(
        p
        for p in (SCOPE if src is None else src).rglob("*.py")
        if "__pycache__" not in p.parts and not _is_test_path(p)
    )


def _counter_assignment(node: ast.AST) -> str | None:
    """``<name>.<counter> = len(<name>.<field>_ids)`` -> the counted field.

    Both halves must name the SAME record: `a.n = len(b.line_ids)` counts b's
    lines onto a and is not a field on the record being counted.
    """
    if not (isinstance(node, ast.Assign) and len(node.targets) == 1):
        return None
    target, value = node.targets[0], node.value
    if not (isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name)):
        return None
    if not (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Name)
        and value.func.id == "len"
        and len(value.args) == 1
    ):
        return None
    arg = value.args[0]
    if not (isinstance(arg, ast.Attribute) and isinstance(arg.value, ast.Name)):
        return None  # multi-hop: not a field on this record, so not a Count
    if arg.value.id != target.value.id:
        return None
    return arg.attr if arg.attr.endswith(RELATIONAL_SUFFIX) else None


def _guards_unsaved(test: ast.AST) -> bool:
    """Whether an ``if`` test is asking "are these records unsaved?".

    ``not any(self._ids)`` is the spelling in the tree; a `NewId` mentioned by
    name counts too. Deliberately textual: the question is whether the author
    branched on it, not what the expression evaluates to.
    """
    src = ast.unparse(test)
    return "self._ids" in src or "NewId" in src


def _loops_over_self(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.For)
        and isinstance(node.iter, ast.Name)
        and node.iter.id == "self"
    )


def measure(
    files: list[Path] | None = None,
    src: Path | None = None,
) -> list[HandCount]:
    if files is None:
        files = iter_source_files(src)
        if not files:
            raise RuntimeError(
                f"no Python sources under {SCOPE if src is None else src} -- the "
                f"scan found nothing, which is not the same as finding nothing wrong"
            )
    found: list[HandCount] = []
    for path in files:
        try:
            tree = ast.parse(path.read_bytes())
        except SyntaxError:
            continue
        display = _display(path)
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not fn.name.startswith("_compute"):
                continue
            # Walked with a flag rather than `ast.walk`, because whether a
            # `len()` is under a NewId guard is a property of its ANCESTORS and
            # a flat walk cannot see them.
            stack: list[tuple[ast.AST, bool]] = [(fn, False)]
            while stack:
                node, unsaved = stack.pop()
                for child in ast.iter_child_nodes(node):
                    child_unsaved = unsaved or (
                        isinstance(node, ast.If)
                        and child in node.body
                        and _guards_unsaved(node.test)
                    )
                    if (
                        field := _counter_assignment(child)
                    ) is not None and not child_unsaved:
                        found.append(
                            HandCount(
                                display, child.lineno, "len", f"{fn.name} -> {field}"
                            )
                        )
                    stack.append((child, child_unsaved))
            for node in ast.walk(fn):
                if not _loops_over_self(node):
                    continue
                found.extend(
                    HandCount(display, inner.lineno, "search_count", fn.name)
                    for inner in ast.walk(node)
                    if isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Attribute)
                    and inner.func.attr == "search_count"
                )
    found.sort(key=lambda f: (f.file, f.line))
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", action="store_true", help="print the count only")
    parser.add_argument("--json", action="store_true", help="machine-readable")
    parser.add_argument("--top", type=int, default=25, help="0 for all")
    parser.add_argument(
        "--addon",
        default=DEFAULT_ADDON,
        help=(
            f"what to measure: {DEFAULT_ADDON} (default) is the odoo/ package, "
            f"{ALL_ADDONS} is the whole bundled-addons tree as one number, "
            f"{' and '.join(SIBLING_SCOPES)} are sibling checkouts, and "
            f"anything else is that one module under addons/"
        ),
    )
    args = parser.parse_args(argv)

    if args.addon not in GOVERNED_ADDONS:
        print(
            f"error: {args.addon!r} is not a governed scope. Onboarding one is a "
            f"row in GOVERNED_ADDONS and its own baseline, not a flag: a floor "
            f"over an unscanned tree checks nothing.\n"
            f"       governed: {', '.join(GOVERNED_ADDONS)}",
            file=sys.stderr,
        )
        return 2

    src = addon_src(args.addon)
    if args.addon in SIBLING_SCOPES and not src.is_dir():
        # Absent, not empty. A single-repo checkout cannot judge a sibling, and
        # printing 0 would hand the ratchet a number that fails the floor while
        # looking like the tree improved.
        print(
            f"SKIP: {args.addon} is not checked out beside {ROOT.name}; "
            f"its own architecture.yml pairs the two and runs this there.",
            file=sys.stderr,
        )
        return 0

    try:
        found = measure(src=src)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.count:
        print(len(found))
        return 0
    if args.json:
        print(json.dumps([asdict(f) for f in found], indent=2))
        return 0

    where = {DEFAULT_ADDON: "odoo/", ALL_ADDONS: "addons/"}.get(
        args.addon,
        f"{args.addon}/" if args.addon in SIBLING_SCOPES else f"addons/{args.addon}/",
    )
    print(f"Counters that count by hand (ADR-0052, {where})")
    print("=" * 72)
    shown = found if args.top == 0 else found[: args.top]
    for item in shown:
        print(item)
    if len(found) > len(shown):
        print(f"  ... and {len(found) - len(shown)} more (--top 0 for all)")
    print("-" * 72)
    by_kind = {k: sum(1 for f in found if f.kind == k) for k in ("len", "search_count")}
    print(f"\n{len(found)} counter(s)   <- the ratcheted number")
    print(
        f"  len(x2many): {by_kind['len']}   search_count in a loop: {by_kind['search_count']}"
    )
    suffix = "" if args.addon == DEFAULT_ADDON else f" --addon {args.addon}"
    name = (
        "py_x2many_count"
        if args.addon == DEFAULT_ADDON
        else f"py_x2many_count_{args.addon}"
    )
    print("\nRatchet it:")
    print(f"  python tooling/architecture/py_x2many_count.py --count{suffix} \\")
    print(f"      | xargs python tooling/ratchet/ratchet.py {name} --count")
    return 0


if __name__ == "__main__":
    sys.exit(main())

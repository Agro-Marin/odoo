#!/usr/bin/env python3
"""A ``search_count`` whose answer is only ever a yes or a no (ADR-0057).

``search_count(domain)`` scans every matching row and returns how many there
are. When the caller then asks only whether that number is nonzero -- ``if``,
``not``, ``bool()``, a comparison against 0 -- the count is discarded and the
scan bought nothing. ``search_count(domain, limit=1)`` answers the same question
and stops at the first row.

The cost is proportional to the table, so it is invisible on a development
database and grows without bound on a real one. Measured on this fork against
``ir.model.fields`` at 8,001 rows, best of twenty with the cache invalidated
between runs::

    search_count([])            0.248 ms
    search_count([], limit=1)   0.053 ms     4.7x

That ratio is not the point -- the shape of the curve is. One is O(rows) and the
other is O(1), so the same call on a production ``account.move.line`` costs
whatever that table has grown to.

WHAT IT COUNTS. A ``search_count`` call passing no ``limit`` whose result reaches
exactly one of: the test of an ``if`` or a conditional expression, ``not``,
``bool()``, or a comparison against the literal ``0``. Each of those is decided
by the same node that produced the count, so the judgement is local and the
rewrite is one keyword.

``and``, ``or`` and ``not`` are walked THROUGH rather than stopped at, because
they pass a value on rather than consuming one. In::

    if combo_item and Template.sudo().search_count(domain):

the count reaches an ``if`` and nothing else, so its number is as discarded as it
would be without the ``and``. ADR-0057 excluded this shape when it was written,
on the ground that the value escapes -- and it does, but only when the
EXPRESSION escapes. Assign the same thing to a name and the walk stops at the
assignment, which is the case that record was really describing.

WHAT IT DOES NOT COUNT, and must not. A count whose enclosing expression is
consumed for anything but its truth: ``vals = a and self.search_count(domain)``
hands the number on, and ``limit=1`` would make it a 1. Nor a count already
passing a ``limit``, which is the fixed form. Nor ``search_count`` used for its
number, however small the table is expected to be -- the gate judges the use,
not the guess.

Tests are out of scope, as they are for the other Python gates here: the cost
this measures is what a server pays serving a request, and a floor that mixed
that with a fixture of four rows would move for reasons nobody could read.
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

ADR = "0057"

ROOT = find_odoo_root(Path(__file__).resolve(), tool="py_count_as_boolean")

SCOPE = ROOT / "odoo"

DEFAULT_ADDON = "core"

ALL_ADDONS = "addons"

SIBLING_SCOPES = ("enterprise", "agromarin")

GOVERNED_ADDONS = (DEFAULT_ADDON, ALL_ADDONS, *SIBLING_SCOPES)

METHOD = "search_count"


def addon_src(addon: str = DEFAULT_ADDON) -> Path:
    if addon == DEFAULT_ADDON:
        return SCOPE
    if addon == ALL_ADDONS:
        return ROOT / "addons"
    if addon in SIBLING_SCOPES:
        return sibling_repos_root(ROOT) / addon
    return ROOT / "addons" / addon


@dataclass(frozen=True)
class Offence:
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


def _truth_use(call: ast.Call, parent: ast.AST | None) -> str | None:
    """How the parent consumes the count, when it consumes only its truth."""
    if isinstance(parent, (ast.If, ast.IfExp)) and parent.test is call:
        return "if"
    if isinstance(parent, ast.UnaryOp) and isinstance(parent.op, ast.Not):
        return "not"
    if (
        isinstance(parent, ast.Call)
        and isinstance(parent.func, ast.Name)
        and parent.func.id == "bool"
    ):
        return "bool()"
    if isinstance(parent, ast.Compare) and len(parent.ops) == 1:
        other = parent.comparators[0] if parent.left is call else parent.left
        if isinstance(other, ast.Constant) and other.value == 0:
            return "vs 0"
    if isinstance(parent, (ast.While, ast.Assert)) and getattr(parent, "test", None) is call:
        return "if"
    return None


def _consumer(call: ast.Call, parents: dict[int, ast.AST]) -> str | None:
    """Walk up until something either uses the number or only its truth.

    `and`/`or`/`not` do not consume a value, they pass one on: in
    ``if combo_item and Template.search_count(domain):`` the count reaches an
    ``if`` and nothing else, so the number is as discarded as it would be
    without the ``and``. Assign that same expression to a name and it is not --
    which is why this walks rather than looking at the immediate parent alone.
    """
    node: ast.AST = call
    while True:
        parent = parents.get(id(node))
        use = _truth_use(node, parent)
        if use:
            return use
        if isinstance(parent, ast.BoolOp) or (
            isinstance(parent, ast.UnaryOp) and isinstance(parent.op, ast.Not)
        ):
            node = parent
            continue
        return None


def measure(
    files: list[Path] | None = None,
    src: Path | None = None,
) -> list[Offence]:
    if files is None:
        files = iter_source_files(src)
        if not files:
            raise RuntimeError(
                f"no Python sources under {SCOPE if src is None else src} -- the "
                f"scan found nothing, which is not the same as finding nothing wrong"
            )
    found: list[Offence] = []
    for path in files:
        try:
            tree = ast.parse(path.read_bytes())
        except SyntaxError:
            continue
        parents: dict[int, ast.AST] = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[id(child)] = node
        display = _display(path)
        for call in ast.walk(tree):
            if not (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == METHOD
            ):
                continue
            if len(call.args) > 1 or any(k.arg == "limit" for k in call.keywords):
                continue
            use = _consumer(call, parents)
            if use:
                found.append(
                    Offence(display, call.lineno, use, ast.unparse(call)[:70])
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
            f"{ALL_ADDONS} is the whole bundled-addons tree as one number, and "
            f"{' and '.join(SIBLING_SCOPES)} are sibling checkouts"
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
        args.addon, f"{args.addon}/"
    )
    print(f"Counts asked only whether they are nonzero (ADR-0057, {where})")
    print("=" * 72)
    shown = found if args.top == 0 else found[: args.top]
    for item in shown:
        print(item)
    if len(found) > len(shown):
        print(f"  ... and {len(found) - len(shown)} more (--top 0 for all)")
    print("-" * 72)
    print(f"\n{len(found)} site(s)   <- the ratcheted number")
    print("  each is one keyword: search_count(domain, limit=1)")
    suffix = "" if args.addon == DEFAULT_ADDON else f" --addon {args.addon}"
    name = (
        "py_count_as_boolean"
        if args.addon == DEFAULT_ADDON
        else f"py_count_as_boolean_{args.addon}"
    )
    print("\nRatchet it:")
    print(f"  python tooling/architecture/py_count_as_boolean.py --count{suffix} \\")
    print(f"      | xargs python tooling/ratchet/ratchet.py {name} --count")
    return 0


if __name__ == "__main__":
    sys.exit(main())

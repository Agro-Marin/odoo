#!/usr/bin/env python3
"""A class body defines each member once.

A second `def` of a name already defined in the same class body silently wins:
Python keeps the last, the earlier one becomes unreachable, and nothing about
the file says so. It is the shape a parallel edit produces when two sessions
add the same method at opposite ends of a long class -- no diff conflict, no
failing test, and the surviving implementation is whichever happens to sit
lower in the file.

`ruff` selects F811 for exactly this, and it does not fire here: the default
`lint.dummy-variable-rgx` matches any leading-underscore name and removes it
from redefinition analysis. In an Odoo model essentially every method is
`_`-prefixed, so F811 covers none of them. Tightening that regex is not the fix
-- it is shared by RUF059, B007, F841, ARG and PLW0128, and measured over this
tree it turns two hard-zero scopes (`odoo/`, `tooling/ tests/`) into 280 and
131 findings to catch a single redefinition.

Redefining a *module-level* class is not in scope: `test_orm` and
`test_inherit` do it deliberately, and a fixture that redeclares a model is not
a shadowed member. Neither is a family that redefines a name on purpose: `@overload` stubs and
the undecorated implementation they precede, a `@property` with its
`.setter`/`.getter`/`.deleter`, and a `functools.singledispatch`
`.register`. A bare `def` after a `@property` is not one of those -- it is
the accident, and it is reported.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _sources
from _repo_root import find_odoo_root, sibling_repos_root

ADR = "0062"

ROOT = find_odoo_root(Path(__file__).resolve(), tool="py_shadowed_member")

SCOPE = ROOT / "odoo"

DEFAULT_ADDON = "core"

ALL_ADDONS = "addons"

SIBLING_SCOPES = ("enterprise", "agromarin", "design-themes")

GOVERNED_ADDONS = (DEFAULT_ADDON, ALL_ADDONS, *SIBLING_SCOPES)

# An @overload stub does not define the member -- the undecorated
# implementation that follows the stubs does. So neither the stubs nor that
# implementation is a shadow.
OVERLOAD_DECORATORS = frozenset({"overload", "typing.overload"})

# These name the member they extend, so the redefinition declares itself.
# @property is deliberately NOT here: a bare `def` after one is the accident.
SELF_DECLARING_SUFFIXES = (".setter", ".getter", ".deleter", ".register")


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
    klass: str
    member: str
    first: int

    def __str__(self) -> str:
        return (
            f"  {self.file}:{self.line}  {self.klass}.{self.member}  "
            f"shadows the definition at line {self.first}"
        )


def iter_source_files(src: Path) -> list[Path]:
    return sorted(p for p in src.rglob("*.py") if "__pycache__" not in p.parts)


def _kind(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    names = {ast.unparse(d).split("(")[0] for d in node.decorator_list}
    if names & OVERLOAD_DECORATORS:
        return "overload"
    if any(name.endswith(SELF_DECLARING_SUFFIXES) for name in names):
        return "declares-itself"
    return "plain"


def _members(body: list[ast.stmt]) -> list[tuple[str, int, str]]:
    # Every binding is recorded, kind and all. Skipping the deliberate ones
    # outright would hide the case this gate is for: a @property redefined
    # later by a bare `def` still shadows.
    named: list[tuple[str, int, str]] = []
    for statement in body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            named.append((statement.name, statement.lineno, _kind(statement)))
        elif isinstance(statement, ast.ClassDef):
            named.append((statement.name, statement.lineno, "plain"))
        elif isinstance(statement, ast.Assign):
            named.extend(
                (target.id, statement.lineno, "plain")
                for target in statement.targets
                if isinstance(target, ast.Name)
            )
    return named


def scan(path: Path, display: str) -> list[Offence]:
    try:
        tree = ast.parse(path.read_bytes())
    except SyntaxError:
        return []
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        seen: dict[str, int] = {}
        stubbed: set[str] = set()
        for name, line, kind in _members(node.body):
            shadows = name in seen and kind != "declares-itself"
            if shadows and name not in stubbed:
                found.append(Offence(display, line, node.name, name, seen[name]))
            if kind == "overload":
                stubbed.add(name)
            else:
                stubbed.discard(name)
            seen.setdefault(name, line)
    return found


def measure(src: Path | None = None) -> list[Offence]:
    where = SCOPE if src is None else src
    files = iter_source_files(where)
    if not files:
        raise RuntimeError(
            f"no Python sources under {where} -- the scan found nothing, which "
            f"is not the same as finding nothing wrong"
        )
    found: list[Offence] = []
    for path in files:
        found.extend(scan(path, _sources.display(path, ROOT)))
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
            f"{', '.join(SIBLING_SCOPES)} are sibling checkouts"
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
    print(f"A class body defines each member once (ADR-{ADR}, {where})")
    print("=" * 72)
    shown = found if args.top == 0 else found[: args.top]
    for item in shown:
        print(item)
    if len(found) > len(shown):
        print(f"  ... and {len(found) - len(shown)} more (--top 0 for all)")
    print("-" * 72)
    print(f"\n{len(found)} shadowed member(s)   <- the ratcheted number")
    print("  each is one definition that never runs")
    suffix = "" if args.addon == DEFAULT_ADDON else f" --addon {args.addon}"
    name = (
        "py_shadowed_member"
        if args.addon == DEFAULT_ADDON
        else f"py_shadowed_member_{args.addon}"
    )
    print("\nRatchet it:")
    print(f"  python tooling/architecture/py_shadowed_member.py --count{suffix} \\")
    print(f"      | xargs python tooling/ratchet/ratchet.py {name} --count")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""``self._something()`` whose definition is nowhere in the checkout (ADR-0058).

A call to a private method that no class in this tree defines is one of three
things: a typo, a method deleted from under its caller, or a reach into a base
that lives outside the repository. The first two are defects that only fail when
the branch runs -- which for an error path can be never -- and the third is
legitimate and finite.

So the third is enumerated rather than guessed. :data:`EXTERNAL` names the
attributes reached on a receiver whose class this scan cannot see: a stdlib or
third-party base, or a namedtuple. **An entry there is a claim that the receiver
is external, so check the call site before adding one** -- "I could not find it"
is the finding, not the excuse for silencing it.

SCOPE IS ``odoo/`` AND ``addons/`` TOGETHER, and unlike its sibling counters this
one does NOT exclude test files: 7 of the floored 25 findings sit under `tests/`
(`addons/sale_mrp/tests/test_sale_mrp_flow.py`, `odoo/tests/suite.py`, …). A test
calling a method that no longer exists is the same defect as production code
doing it, and arguably worse, because the test then cannot fail for the reason it
was written.
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
from _repo_root import find_odoo_root

ADR = "0058"

ROOT = find_odoo_root(Path(__file__).resolve(), tool="py_unresolved_calls")

SCOPES = (ROOT / "odoo", ROOT / "addons")

# Attributes reached on an object this scan cannot see the class of: a stdlib or
# third-party base, or a namedtuple. Each is a call the gate would otherwise report
# forever, because the definition is real and simply lives outside the checkout.
# An entry here is a claim that the receiver is external -- check the call site
# before adding one, since "I could not find it" is the finding, not the excuse.
EXTERNAL: frozenset[str] = frozenset(
    {
        "_add_object",  # pypdf writer, subclassed in tools/pdf
        "_ansi_style",  # werkzeug.serving
        "_asdict",  # namedtuple
        "_build_localename",  # locale
        "_create_stdlib_context",  # ssl
        "_current_frames",  # sys
        "_exit",  # os
        "_formatMessage",  # unittest.TestCase
        "_getframe",  # sys
        "_load_region",  # phonenumbers
    }
)


@dataclass(frozen=True)
class UnresolvedCall:
    file: str
    line: int
    name: str
    source: str

    def __str__(self) -> str:
        return f"  {self.file}:{self.line}  {self.name}\n      {self.source}"


def iter_source_files(scopes: tuple[Path, ...] = SCOPES) -> list[Path]:
    return sorted(
        p
        for scope in scopes
        for p in scope.rglob("*.py")
        if "__pycache__" not in p.parts
    )


def measure(scopes: tuple[Path, ...] = SCOPES) -> list[UnresolvedCall]:
    """Every `x._name(...)` whose `_name` this checkout defines nowhere.

    A name counts as defined by a `def`/`class` anywhere in scope, by an attribute
    assignment (`obj._name = ...`, which is how a slot or a patched-in callable is
    bound), or by appearing as a string literal (`__slots__`, `getattr`). Those three
    are what separate a vanished method from a live one reached indirectly.
    """
    files = iter_source_files(scopes)
    if not files:
        raise RuntimeError(
            f"no Python sources under {', '.join(str(s) for s in scopes)} -- the "
            f"scan found nothing, which is not the same as finding nothing wrong"
        )

    defined: set[str] = set()
    bound: set[str] = set()
    calls: list[tuple[Path, ast.Call, str]] = []
    trees: list[tuple[Path, ast.Module, list[str]]] = []

    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        trees.append((path, tree, text.splitlines()))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                defined.add(node.name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Attribute):
                        bound.add(target.attr)
                    elif isinstance(target, ast.Name):
                        bound.add(target.id)
            elif isinstance(node, ast.AnnAssign) and isinstance(
                node.target, ast.Attribute
            ):
                bound.add(node.target.attr)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                bound.add(node.value)

    for path, tree, lines in trees:
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(
                node.func, ast.Attribute
            ):
                continue
            name = node.func.attr
            if not name.startswith("_") or name.startswith("__"):
                continue
            calls.append((path, node, lines[node.lineno - 1].strip()))

    found = [
        UnresolvedCall(_sources.display(path, ROOT), node.lineno, node.func.attr, source)
        for path, node, source in calls
        if node.func.attr not in defined
        and node.func.attr not in bound
        and node.func.attr not in EXTERNAL
    ]
    found.sort(key=lambda c: (c.name, c.file, c.line))
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", action="store_true", help="print the count only")
    parser.add_argument("--json", action="store_true", help="machine-readable")
    parser.add_argument("--top", type=int, default=30, help="0 for all")
    args = parser.parse_args(argv)

    try:
        found = measure()
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.count:
        print(len(found))
        return 0
    if args.json:
        print(json.dumps([asdict(c) for c in found], indent=2))
        return 0

    print("Calls to methods this checkout defines nowhere (ADR-0058)")
    print("=" * 72)
    shown = found if args.top == 0 else found[: args.top]
    for item in shown:
        print(item)
    if len(found) > len(shown):
        print(f"  ... and {len(found) - len(shown)} more (--top 0 for all)")
    print("-" * 72)
    names = sorted({c.name for c in found})
    print(f"\n{len(found)} call site(s) over {len(names)} name(s)")
    print(f"  {len(EXTERNAL)} name(s) allowed as external, see EXTERNAL")
    print("\nRatchet it:")
    print("  python tooling/architecture/py_unresolved_calls.py --count \\")
    print("      | xargs python tooling/ratchet/ratchet.py unresolved_calls --count")
    return 0


if __name__ == "__main__":
    sys.exit(main())

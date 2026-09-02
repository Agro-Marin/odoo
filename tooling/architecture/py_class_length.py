#!/usr/bin/env python3
"""Ratchet the mass a function-length budget cannot see.

py_function_length.py holds every function under 90 lines, and the core package is
at zero excess -- yet tools/config.py's configmanager is 2,035 lines over 104
methods and tools/translate.py bundles five concerns in one module, because a
class of short methods is invisible to a per-function budget. This gate measures
classes: a class body longer than MAX_LINES is an offender, and the unit is the
EXCESS above the budget summed over offenders, the same unit as pyfunclen and for
the same reason -- splitting one huge class into two large ones raises the
offender count while lowering the excess, and the count metric would refuse that
improvement. Scopes mirror py_function_length.py: core is the odoo/ package,
addons the bundled tree as one number (driven --mode no-increase because it moves
both ways constantly), and any addon name under addons/ its own budget.
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _ast_cache

ROOT = find_odoo_root(Path(__file__).resolve(), tool="py_class_length")
SCOPE = ROOT / "odoo"
DEFAULT_ADDON = "core"
ALL_ADDONS = "addons"
TOOLING = "tooling"
TESTS = "tests"

MAX_LINES = 400


def addon_src(addon: str = DEFAULT_ADDON) -> Path:
    if addon == DEFAULT_ADDON:
        return SCOPE
    if addon == ALL_ADDONS:
        return ROOT / "addons"
    if addon == TOOLING:
        return ROOT / "tooling"
    if addon == TESTS:
        return SCOPE / "tests"
    return ROOT / "addons" / addon


@dataclass(frozen=True)
class LongClass:
    file: str
    line: int
    lines: int
    what: str

    def __str__(self) -> str:
        return f"  {self.lines:5d}  {self.file}:{self.line}  {self.what}"


def iter_source_files(src: Path | None = None) -> list[Path]:
    root = SCOPE if src is None else src
    return _sources.iter_python_files(root, include_tests=root == SCOPE / "tests")


def measure(
    files: list[Path] | None = None,
    src: Path | None = None,
) -> list[LongClass]:
    if files is None:
        files = iter_source_files(src)
        if not files:
            raise RuntimeError(
                f"no Python sources under {SCOPE if src is None else src} -- the "
                f"scan found nothing, which is not the same as finding nothing wrong"
            )
    found: list[LongClass] = []
    for path in files:
        tree = _ast_cache.parse_file(path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef) or node.end_lineno is None:
                continue
            length = node.end_lineno - node.lineno + 1
            if length > MAX_LINES:
                found.append(
                    LongClass(
                        file=_sources.display(path, ROOT),
                        line=node.lineno,
                        lines=length,
                        what=node.name,
                    )
                )
    found.sort(key=lambda c: (-c.lines, c.file, c.line))
    return found


def excess_lines(found: list[LongClass]) -> int:
    return sum(c.lines - MAX_LINES for c in found)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--count", action="store_true", help="print the count only")
    parser.add_argument("--json", action="store_true", help="machine-readable")
    parser.add_argument("--top", type=int, default=20, help="0 for all")
    parser.add_argument(
        "--addon",
        default=DEFAULT_ADDON,
        help=(
            f"what to measure: {DEFAULT_ADDON} (default) is the odoo/ package, "
            f"{ALL_ADDONS} is the whole bundled-addons tree as one number, "
            f"{TOOLING} is the gates themselves, {TESTS} is the test framework "
            f"under odoo/tests/, and anything else is that one module under "
            f"addons/"
        ),
    )
    args = parser.parse_args(argv)

    try:
        found = measure(src=addon_src(args.addon))
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.count:
        print(excess_lines(found))
        return 0
    if args.json:
        print(json.dumps([asdict(c) for c in found], indent=2))
        return 0

    where = {
        DEFAULT_ADDON: "odoo/",
        ALL_ADDONS: "addons/",
        TOOLING: "tooling/",
        TESTS: "odoo/tests/",
    }.get(args.addon, f"addons/{args.addon}/")
    print(f"Python class-length budget (> {MAX_LINES} lines, {where})")
    print("=" * 72)
    shown = found if args.top == 0 else found[: args.top]
    for item in shown:
        print(item)
    if len(found) > len(shown):
        print(f"  ... and {len(found) - len(shown)} more (--top 0 for all)")
    print("-" * 72)
    print(f"{len(found)} class(es) over budget, {excess_lines(found)} excess line(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

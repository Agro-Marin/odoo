#!/usr/bin/env python3
"""Function-length budget for the Python core — the missing half of a pair.

`js_function_length.py` has budgeted JavaScript functions at 80 lines and
ratcheted the count since 2026-07. Python had no equivalent, and nothing else
covered it: `c901` measures *cyclomatic complexity*, so a long straight-line
function scores near zero, and ruff's length rules are not enabled.

That gap was not theoretical. `configmanager._build_cli` stood at **1024
lines** — 4.6x the next-longest function in the core — built almost entirely
from consecutive `parser.add_option(...)` calls, so its branch count was
trivial and every gate reported it clean. Measured when this landed, across
6208 functions under `odoo/`: median 7 lines, p95 55, three over 200.

Same design as the JS gate with **one deliberate difference**: the ratcheted
number is the *excess* — the total lines above budget, ``sum(len - 80)`` — not
the *count* of offending functions. The JS gate counts functions, and that
metric punishes the exact fix it exists to encourage. Splitting ``_build_cli``
measured:

    metric          before    after
    count > 80         121      127     <- worse
    excess lines      5457     4867     <- better by 590
    longest           1024      294     <- better by 730

One 1024-line function became eleven methods, four of which are still over 80,
so the count rose by six while every honest measure of the problem improved. A
count ratchet would have rejected that change as a regression. Excess falls
whenever code is genuinely split and rises only when a function actually grows,
which is the property a budget needs. (The same objection applies to
``jsfunclen``; changing it is a separate move, on a separate baseline.)

Otherwise:

* **80 lines**, counting every line the function spans. Skipping blanks or
  comments would let a long function hide behind its own documentation, and the
  budget is about how much a reader must hold at once.
* **No single function is blocked.** The ratcheted total may only fall. A gate
  that rejected the 81st line of one function would be argued with per
  function, which is how budgets die.
* Tests are out of scope. A long test is usually a table of cases, and the
  cost a long *implementation* imposes — that a reader must hold it all to
  change it safely — does not apply the same way.

Usage::

  python tooling/architecture/py_function_length.py            # report
  python tooling/architecture/py_function_length.py --count    # for the ratchet
  python tooling/architecture/py_function_length.py --json
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

ROOT = find_odoo_root(Path(__file__).resolve(), tool="py_function_length")

#: The core package, matching `ruff` and `c901`'s scope. `addons/` is budgeted
#: separately or not at all, exactly as `c901`/`c901_addons` split it.
SCOPE = ROOT / "odoo"

MAX_LINES = 80


@dataclass(frozen=True)
class LongFunction:
    file: str
    line: int
    lines: int
    what: str

    def __str__(self) -> str:
        return f"  {self.lines:5d}  {self.file}:{self.line}  {self.what}"


def _display(path: Path) -> str:
    """Repo-relative where possible; absolute for a file injected by a test."""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _is_test_path(path: Path) -> bool:
    return "tests" in path.parts or path.name.startswith("test_")


def iter_source_files() -> list[Path]:
    return sorted(
        p
        for p in SCOPE.rglob("*.py")
        if "__pycache__" not in p.parts and not _is_test_path(p)
    )


def measure(files: list[Path] | None = None) -> list[LongFunction]:
    """Every function over :data:`MAX_LINES`, longest first.

    Raises when a *scan of the real tree* finds no source at all: an excess of
    0 is what a perfectly-split codebase looks like, and the ratchet runs in
    exact mode, so a scan that silently found nothing would either read as a
    triumph or fail against the floor for the wrong reason. An explicit empty
    ``files`` list is a caller passing nothing on purpose, and is not an error.
    """
    if files is None:
        files = iter_source_files()
        if not files:
            raise RuntimeError(
                f"no Python sources under {SCOPE} -- the scan found nothing, "
                f"which is not the same as finding nothing wrong"
            )
    found: list[LongFunction] = []
    for path in files:
        try:
            tree = ast.parse(path.read_bytes())
        except SyntaxError:
            # A file the interpreter would reject is a different problem, and
            # not this gate's to report.
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.end_lineno is None:
                continue
            # `node.lineno` is the `def`, not the first decorator: a function
            # is not made long by being decorated.
            length = node.end_lineno - node.lineno + 1
            if length > MAX_LINES:
                found.append(
                    LongFunction(
                        file=_display(path),
                        line=node.lineno,
                        lines=length,
                        what=node.name,
                    )
                )
    found.sort(key=lambda f: (-f.lines, f.file, f.line))
    return found


def excess_lines(found: list[LongFunction]) -> int:
    """Total lines above budget — the ratcheted number. See the module docstring."""
    return sum(f.lines - MAX_LINES for f in found)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", action="store_true", help="print the count only")
    parser.add_argument("--json", action="store_true", help="machine-readable")
    parser.add_argument("--top", type=int, default=20, help="0 for all")
    args = parser.parse_args(argv)

    try:
        found = measure()
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.count:
        print(excess_lines(found))
        return 0
    if args.json:
        print(json.dumps([asdict(f) for f in found], indent=2))
        return 0

    print(f"Python function-length budget (> {MAX_LINES} lines, odoo/)")
    print("=" * 72)
    shown = found if args.top == 0 else found[: args.top]
    for item in shown:
        print(item)
    if len(found) > len(shown):
        print(f"  ... and {len(found) - len(shown)} more (--top 0 for all)")
    print("-" * 72)
    over = {t: sum(1 for f in found if f.lines > t) for t in (150, 250, 400)}
    print(f"\n{len(found)} function(s) over {MAX_LINES} lines")
    print(f"  over 150: {over[150]}   over 250: {over[250]}   over 400: {over[400]}")
    print(f"  longest: {found[0].lines if found else 0}")
    print(
        f"\nexcess lines above budget: {excess_lines(found)}   <- the ratcheted number"
    )
    print("\nRatchet it:")
    print("  python tooling/architecture/py_function_length.py --count \\")
    print("      | xargs python tooling/ratchet/ratchet.py pyfunclen --count")
    return 0


if __name__ == "__main__":
    sys.exit(main())

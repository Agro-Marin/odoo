#!/usr/bin/env python3
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

ADR = "0025"

ROOT = find_odoo_root(Path(__file__).resolve(), tool="py_function_length")

SCOPE = ROOT / "odoo"

DEFAULT_ADDON = "core"

ALL_ADDONS = "addons"

TOOLING = "tooling"


def addon_src(addon: str = DEFAULT_ADDON) -> Path:
    if addon == DEFAULT_ADDON:
        return SCOPE
    if addon == ALL_ADDONS:
        return ROOT / "addons"
    if addon == TOOLING:
        return ROOT / "tooling"
    return ROOT / "addons" / addon


MAX_LINES = 80


@dataclass(frozen=True)
class LongFunction:
    file: str
    line: int
    lines: int
    what: str

    def __str__(self) -> str:
        return f"  {self.lines:5d}  {self.file}:{self.line}  {self.what}"


def iter_source_files(src: Path | None = None) -> list[Path]:
    return _sources.iter_python_files(SCOPE if src is None else src)


def measure(
    files: list[Path] | None = None,
    src: Path | None = None,
) -> list[LongFunction]:

    if files is None:
        files = iter_source_files(src)
        if not files:
            raise RuntimeError(
                f"no Python sources under {SCOPE if src is None else src} -- the "
                f"scan found nothing, which is not the same as finding nothing wrong"
            )
    found: list[LongFunction] = []
    for path in files:
        try:
            tree = ast.parse(path.read_bytes())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.end_lineno is None:
                continue
            length = node.end_lineno - node.lineno + 1
            if length > MAX_LINES:
                found.append(
                    LongFunction(
                        file=_sources.display(path, ROOT),
                        line=node.lineno,
                        lines=length,
                        what=node.name,
                    )
                )
    found.sort(key=lambda f: (-f.lines, f.file, f.line))
    return found


def excess_lines(found: list[LongFunction]) -> int:
    return sum(f.lines - MAX_LINES for f in found)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", action="store_true", help="print the count only")
    parser.add_argument("--json", action="store_true", help="machine-readable")
    parser.add_argument("--top", type=int, default=20, help="0 for all")
    parser.add_argument(
        "--addon",
        default=DEFAULT_ADDON,
        help=(
            f"what to measure: {DEFAULT_ADDON} (default) is the odoo/ package, "
            f"{ALL_ADDONS} is the whole bundled-addons tree as one number, "
            f"{TOOLING} is the gates themselves, and anything else is that one "
            f"module under addons/"
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
        print(json.dumps([asdict(f) for f in found], indent=2))
        return 0

    where = {DEFAULT_ADDON: "odoo/", ALL_ADDONS: "addons/", TOOLING: "tooling/"}.get(
        args.addon, f"addons/{args.addon}/"
    )
    print(f"Python function-length budget (> {MAX_LINES} lines, {where})")
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
    suffix = "" if args.addon == DEFAULT_ADDON else f" --addon {args.addon}"
    name = "pyfunclen" if args.addon == DEFAULT_ADDON else f"pyfunclen_{args.addon}"
    mode = " --mode no-increase" if args.addon == ALL_ADDONS else ""
    print("\nRatchet it:")
    print(f"  python tooling/architecture/py_function_length.py --count{suffix} \\")
    print(f"      | xargs python tooling/ratchet/ratchet.py {name}{mode} --count")
    return 0


if __name__ == "__main__":
    sys.exit(main())

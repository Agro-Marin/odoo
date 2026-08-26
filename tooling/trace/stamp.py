#!/usr/bin/env python3
"""Stamp (and un-stamp) per-component render probes across a JS tree.

The campaign's choke-point probes in ``@web/core/utils/asset_log`` observe every
module without touching it: module load, registry adds, service waves, RPC,
actions, model operations, view loads and field resolution all funnel through a
handful of files. What they cannot see is *which component re-rendered*, because
that fact only exists inside each component's own ``setup()``.

This tool writes that one probe into every component class in a scope, and takes
it back out again. Both directions are exact: every line it inserts carries the
``SENTINEL`` trailing comment, and ``--revert`` removes lines carrying that
comment and nothing else, so a stamped tree returns byte-identical to its
pre-stamp state.

The probe itself is ``useRenderCounter`` from
``@web/core/utils/render_instrumentation``, which is gated behind
``globalThis.__renderTrace`` and costs one dead ``if`` while that is false.

    python tooling/trace/stamp.py --check
    python tooling/trace/stamp.py --apply
    python tooling/trace/stamp.py --revert

GATE IMPACT IS REPORTED, NOT ABSORBED. A stamp adds one statement line to every
``setup()`` it touches, and ``jsfunclen`` is an exact floor over functions longer
than 80 lines. ``--check`` names every function the stamp would push over that
budget so the scope can be narrowed before the floor moves.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

ROOT = find_odoo_root(Path(__file__).resolve(), tool="stamp")

SENTINEL = "// trace-stamp"
PROBE_MODULE = "@web/core/utils/render_instrumentation"
PROBE_IMPORT = f'import {{ useRenderCounter }} from "{PROBE_MODULE}";'
PRINT_WIDTH = 88

DEFAULT_ROOT = "addons/web/static/src"

CLASS_RE = re.compile(r"^(\s*)(?:export\s+)?class\s+(\w+)\s+extends\s+[\w.]+\s*\{")
SETUP_RE = re.compile(r"^(\s*)setup\s*\(\s*\)\s*\{\s*$")
IMPORT_RE = re.compile(r"^import\s.*;\s*$")
FUNCTION_LINE_BUDGET = 80


def iter_files(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*.js")
        if "/tests/" not in path.as_posix()
        and not path.name.endswith(".test.js")
        and "/lib/" not in path.as_posix()
    )


def label_for(path: Path, class_name: str, qualify: bool = False) -> str:
    stem = re.sub(r"\.js$", "", path.name)
    if qualify:
        stem = f"{path.parent.name}/{stem}"
    return f"{stem}:{class_name}"


def resolve_labels(files: list[Path]) -> dict[tuple[str, str], str]:
    plan: list[tuple[Path, str, str]] = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        if is_hand_instrumented(text):
            continue
        lines = text.splitlines()
        for index, class_name in find_stamp_sites(lines):
            indent = SETUP_RE.match(lines[index]).group(1) + "    "
            plan.append((path, class_name, indent))

    chosen: dict[tuple[str, str], str] = {}
    for path, class_name, indent in plan:
        mid = label_for(path, class_name)
        fits = len(stamped_line(indent, mid)) <= PRINT_WIDTH
        chosen[(path.as_posix(), class_name)] = mid if fits else class_name

    counts: dict[str, int] = {}
    for label in chosen.values():
        counts[label] = counts.get(label, 0) + 1
    for path, class_name, _indent in plan:
        key = (path.as_posix(), class_name)
        if counts[chosen[key]] > 1:
            chosen[key] = label_for(path, class_name, qualify=True)
    return chosen


def import_spans(lines: list[str]) -> list[tuple[int, int, str | None]]:
    spans: list[tuple[int, int, str | None]] = []
    i = 0
    while i < len(lines):
        if re.match(r"^import\s", lines[i]):
            j = i
            while j < len(lines) and not lines[j].rstrip().endswith(";"):
                j += 1
            joined = " ".join(lines[i : j + 1])
            match = re.search(r'from\s+"([^"]+)"', joined) or re.match(
                r'^import\s+"([^"]+)"', lines[i]
            )
            spans.append((i, j, match.group(1) if match else None))
            i = j + 1
        else:
            i += 1
    return spans


def insert_import(lines: list[str]) -> list[str]:
    spans = import_spans(lines)
    if not spans:
        return [f"{PROBE_IMPORT} {SENTINEL}", *lines]

    bare = [(a, b, src) for a, b, src in spans if src and not src.startswith(".")]
    if not bare:
        head = spans[0][0]
        return [*lines[:head], f"{PROBE_IMPORT} {SENTINEL}", *lines[head:]]

    target = next(
        (a for a, _b, src in bare if src and src > PROBE_MODULE), bare[-1][1] + 1
    )
    return [*lines[:target], f"{PROBE_IMPORT} {SENTINEL}", *lines[target:]]


def block_end(lines: list[str], start: int) -> int:
    depth = 0
    for offset in range(start, len(lines)):
        depth += lines[offset].count("{") - lines[offset].count("}")
        if depth <= 0 and offset > start:
            return offset
    return start


def find_stamp_sites(lines: list[str]) -> list[tuple[int, str]]:
    sites: list[tuple[int, str]] = []
    current: str | None = None
    for index, line in enumerate(lines):
        class_match = CLASS_RE.match(line)
        if class_match:
            current = class_match.group(2)
            continue
        setup_match = SETUP_RE.match(line)
        if setup_match and current is not None:
            body = lines[index : block_end(lines, index) + 1]
            if not any(SENTINEL in row for row in body):
                sites.append((index, current))
            current = None
    return sites


def is_hand_instrumented(text: str) -> bool:
    return "useRenderCounter(" in text


def function_lengths(lines: list[str]) -> dict[int, int]:
    lengths: dict[int, int] = {}
    for index, line in enumerate(lines):
        if not SETUP_RE.match(line):
            continue
        end = block_end(lines, index)
        if end > index:
            lengths[index] = end - index + 1
    return lengths


def stamped_line(indent: str, label: str) -> str:
    return f'{indent}useRenderCounter("{label}"); {SENTINEL}'


def apply_to_text(
    text: str, path: Path, labels: dict[tuple[str, str], str]
) -> tuple[str, int, list[str]]:
    if is_hand_instrumented(text):
        return text, 0, []
    lines = text.splitlines()
    sites = find_stamp_sites(lines)
    if not sites:
        return text, 0, []

    over: list[str] = []
    for index, class_name in reversed(sites):
        indent = SETUP_RE.match(lines[index]).group(1) + "    "
        label = labels[(path.as_posix(), class_name)]
        line = stamped_line(indent, label)
        if len(line) > PRINT_WIDTH:
            over.append(f"{path.as_posix()}:{index + 1} ({len(line)} cols)")
        lines.insert(index + 1, line)

    imports = 0
    if PROBE_IMPORT not in text:
        lines = insert_import(lines)
        imports = 1
        line = f"{PROBE_IMPORT} {SENTINEL}"
        if len(line) > PRINT_WIDTH:
            over.append(f"{path.as_posix()}: the probe import ({len(line)} cols)")

    return "\n".join(lines) + "\n", len(sites) + imports, over


def revert_text(text: str) -> tuple[str, int]:
    lines = text.splitlines()
    kept = [line for line in lines if SENTINEL not in line]
    removed = len(lines) - len(kept)
    if not removed:
        return text, 0
    return "\n".join(kept) + "\n", removed


def check(files: list[Path], repo_root: Path) -> int:
    total_sites = 0
    total_files = 0
    hand = 0
    at_risk: list[str] = []
    over_width: list[str] = []
    labels = resolve_labels(files)
    qualified = sum(1 for v in labels.values() if "/" in v)
    for path in files:
        text = path.read_text(encoding="utf-8")
        if is_hand_instrumented(text):
            hand += 1
            continue
        lines = text.splitlines()
        sites = find_stamp_sites(lines)
        if not sites:
            continue
        for index, class_name in sites:
            indent = SETUP_RE.match(lines[index]).group(1) + "    "
            line = stamped_line(indent, labels[(path.as_posix(), class_name)])
            if len(line) > PRINT_WIDTH:
                over_width.append(f"  {path.as_posix()}:{index + 1} ({len(line)} cols)")
        total_files += 1
        total_sites += len(sites)
        lengths = function_lengths(lines)
        for index, class_name in sites:
            length = lengths.get(index)
            if length is not None and length == FUNCTION_LINE_BUDGET:
                rel = path.relative_to(repo_root).as_posix()
                at_risk.append(f"  {rel}:{index + 1} {class_name} ({length} lines)")

    print(f"files with a component setup(): {total_files}")
    print(f"hand-instrumented, left alone: {hand}")
    print(f"stamp sites:                    {total_sites}")
    print(f"labels qualified for collision: {qualified}")
    if over_width:
        print(f"\nOVER prettier's {PRINT_WIDTH}-column width ({len(over_width)}):")
        print("\n".join(over_width))
        print(
            "\nprettier would wrap these, and a wrapped call puts the sentinel on a "
            "line of its own -- which --revert would not fully undo."
        )
    if at_risk:
        print(
            f"\nWOULD CROSS THE {FUNCTION_LINE_BUDGET}-LINE jsfunclen BUDGET "
            f"({len(at_risk)}):"
        )
        print("\n".join(at_risk))
        print(
            "\njsfunclen is an exact floor. Narrow the scope, or re-measure and "
            "bank the floor in the same commit as the stamp."
        )
    else:
        print(f"\nno setup() sits at the {FUNCTION_LINE_BUDGET}-line budget edge")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Stamp per-component render probes across a JS tree.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="write the probes")
    mode.add_argument("--revert", action="store_true", help="remove every probe")
    mode.add_argument(
        "--check",
        action="store_true",
        help="report scope and jsfunclen risk, writing nothing (default)",
    )
    parser.add_argument(
        "--root",
        default=DEFAULT_ROOT,
        help=f"tree to stamp, relative to the odoo checkout (default: {DEFAULT_ROOT})",
    )
    args = parser.parse_args(argv)

    root = ROOT / args.root
    if not root.is_dir():
        print(f"no such tree: {root}", file=sys.stderr)
        return 2

    files = iter_files(root)
    if not (args.apply or args.revert):
        return check(files, ROOT)

    touched = 0
    units = 0
    over_all: list[str] = []
    labels = resolve_labels(files) if args.apply else {}
    for path in files:
        text = path.read_text(encoding="utf-8")
        if args.apply:
            new_text, count, over = apply_to_text(text, path, labels)
            over_all.extend(over)
        else:
            new_text, count = revert_text(text)
        if count:
            path.write_text(new_text, encoding="utf-8")
            touched += 1
            units += count

    verb = "stamped" if args.apply else "removed"
    print(f"{verb} {units} probe line(s) across {touched} file(s)")
    if args.apply:
        if over_all:
            imports_over = [
                o for o in over_all if o.endswith("cols)") and "import" in o
            ]
            sites_over = [o for o in over_all if o not in imports_over]
            print(
                f"\nWARNING: {len(sites_over) + bool(imports_over)} kind(s) of line "
                f"exceed {PRINT_WIDTH} columns:"
            )
            if imports_over:
                print(
                    f"  the probe import, in all {len(imports_over)} file(s) that "
                    f"gained one"
                )
            print("\n".join(f"  {o}" for o in sites_over))
        print(
            "\nRe-measure before committing:\n"
            "  npx eslint <touched files>   # must be CLEAN -- do NOT run --fix,\n"
            "                               # it reflows stamped lines out from\n"
            "                               # under --revert\n"
            "  python tooling/architecture/js_function_length.py --count"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

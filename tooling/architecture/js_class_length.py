#!/usr/bin/env python3
"""Ratchet the JS mass a function-length budget cannot see.

`py_class_length.py` exists because a class of short methods is invisible to a
per-function budget. The client tree has the same shape and had no such gate:
`js_function_length.py` holds every JS function under 90 lines, and
`addons/web/static/src/core/flow_editor/flow_editor.js` still carries one
1,267-line `FlowEditor` component over 63 methods, none of them an offender.
Four more classes there are over 900 lines and 49 are over this budget. Every
one passes `jsfunclen`, `js_layer_check`, `js_face_boundary` and the surface
gates, because none of them measures concentration.

The unit is the EXCESS above `MAX_LINES` summed over offenders, not the offender
count, for the reason `py_class_length.py` gives: splitting one huge class into
two large ones raises the count while lowering the excess, and a count metric
would refuse that improvement. Comment-only lines do not count, so that the
number stays comparable with `jsfunclen`, which runs eslint with
`skipComments: true`.

`MAX_LINES` is 400, the same budget as the Python gate. Scopes mirror
`js_function_length.py`: one governed addon per `--addon`, `web` by default.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

ROOT = find_odoo_root(Path(__file__).resolve(), tool="js_class_length")
WEB_SRC = ROOT / "addons" / "web" / "static" / "src"

GOVERNED_ADDONS = ("web", "mail", "account", "stock", "product", "survey")
DEFAULT_ADDON = "web"

ANALYZER = Path(__file__).with_suffix(".mjs")

MAX_LINES = 400

GENERATED = frozenset({"emoji_data.js"})


def addon_src(addon: str = DEFAULT_ADDON) -> Path:
    return (
        WEB_SRC
        if addon == DEFAULT_ADDON
        else ROOT / "addons" / addon / "static" / "src"
    )


@dataclass(frozen=True)
class LongClass:
    file: str
    line: int
    lines: int
    what: str

    def __str__(self) -> str:
        return f"  {self.lines:5d}  {self.file}:{self.line}  {self.what}"


def iter_source_files(src: Path) -> list[Path]:
    if not src.is_dir():
        return []
    return [
        path
        for path in sorted(src.rglob("*.js"))
        if path.name not in GENERATED and "node_modules" not in path.parts
    ]


def analyse(files: list[Path], src: Path) -> list[LongClass]:
    """Every class in `files`, longest first -- over budget or not."""
    if not files:
        return []
    proc = subprocess.run(
        ["node", str(ANALYZER), *[str(f) for f in files]],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"class-length analyzer failed: {proc.stderr.strip()}")
    found: list[LongClass] = []
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        rel = Path(raw["file"])
        with contextlib.suppress(ValueError):
            rel = rel.resolve().relative_to(src.resolve())
        found.append(LongClass(rel.as_posix(), raw["line"], raw["lines"], raw["what"]))
    return sorted(found, key=lambda c: (-c.lines, c.file, c.line))


def measure(src: Path = WEB_SRC) -> list[LongClass]:
    files = iter_source_files(src)
    if not files:
        raise RuntimeError(
            f"no JavaScript sources under {src} -- the scan found nothing, "
            f"which is not the same as finding nothing wrong"
        )
    return [c for c in analyse(files, src) if c.lines > MAX_LINES]


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
        choices=GOVERNED_ADDONS,
        help="which addon's static/src to measure (default: web)",
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

    print(f"JS class-length budget (> {MAX_LINES} lines, {args.addon}/static/src)")
    print("=" * 72)
    shown = found if args.top == 0 else found[: args.top]
    for item in shown:
        print(item)
    if len(found) > len(shown):
        print(f"  ... and {len(found) - len(shown)} more (--top 0 for all)")
    print("-" * 72)
    print(f"{len(found)} class(es) over budget, {excess_lines(found)} excess line(s)")
    print("\nRatchet this number:")
    suffix = "" if args.addon == DEFAULT_ADDON else f" --addon {args.addon}"
    name = "jsclasslen" if args.addon == DEFAULT_ADDON else f"jsclasslen_{args.addon}"
    print(f"  python tooling/architecture/js_class_length.py{suffix} --count \\")
    print(f"      | xargs python tooling/ratchet/ratchet.py {name} --count")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

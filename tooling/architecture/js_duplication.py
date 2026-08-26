"""Duplicated JavaScript, counted byte-exactly.

Eighteen gates guard this tree's JS -- layering, cycles, import resolution,
function length, private access, service shape, forced renders, public surface,
face boundaries, mixin coupling, export coherence -- and not one of them looks
for a block that exists twice. A copied block passes every one of them, because
each is structurally identical to a block that belongs where it is.

What this counts is **duplicated significant lines between two files**: the
total length of the maximal runs that appear, byte for byte after normalisation,
in more than one file. It is a debt figure to drive down, not a steady state.

Byte-exact on purpose. A normalised-window hash -- the obvious implementation --
scores a *prefix* relationship as duplication, and that overstates the case in a
way that produces wrong findings. Measured on
``calendar_year_renderer.js`` against ``calendar_common_renderer.js``: a window
detector reported 89 duplicated lines across five methods, and byte-level
extraction showed only one method (9 lines) was actually a duplicate. The other
four were prefixes -- the year renderer's body was the head of the common one's,
which is a better argument for extracting and a different number. This gate
reports the number it can defend.

Normalisation is deliberately shallow: blank lines and comment-only lines are
dropped and runs of whitespace are collapsed, so reindenting a block does not
hide it, but renaming a variable does. That is the right trade for a ratchet --
it under-reports rather than crying wolf, and an under-report is a floor that
still only moves down.

    python tooling/architecture/js_duplication.py --top 20
    python tooling/architecture/js_duplication.py --count \\
        | xargs python tooling/ratchet/ratchet.py jsduplication --count
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

ADR = "0045"

ROOT = find_odoo_root(Path(__file__).resolve(), tool="js_duplication")

GOVERNED_ADDONS = ("web",)
DEFAULT_ADDON = "web"

MIN_RUN = 9

GENERATED = frozenset({"emoji_data.js"})


def addon_src(addon: str = DEFAULT_ADDON) -> Path:
    return ROOT / "addons" / addon / "static" / "src"


@dataclass(frozen=True)
class Run:
    lines: int
    left: str
    left_start: int
    left_end: int
    right: str
    right_start: int
    right_end: int


def significant(path: Path) -> list[tuple[int, str]]:
    out = []
    for number, raw in enumerate(
        path.read_text(encoding="utf-8", errors="ignore").split("\n"), start=1
    ):
        text = raw.strip()
        if not text or text.startswith(("//", "*", "/*")):
            continue
        out.append((number, re.sub(r"\s+", " ", text)))
    return out


def js_files(src: Path) -> list[Path]:
    return sorted(
        p
        for p in src.rglob("*.js")
        if "/lib/" not in str(p) and p.name not in GENERATED
    )


def maximal_runs(a: list[tuple[int, str]], b: list[tuple[int, str]]) -> list[Run]:
    index: dict[str, list[int]] = defaultdict(list)
    for i in range(len(b) - MIN_RUN + 1):
        key = hashlib.sha1(
            "\n".join(text for _, text in b[i : i + MIN_RUN]).encode()
        ).hexdigest()
        index[key].append(i)

    runs: list[Run] = []
    i = 0
    while i < len(a) - MIN_RUN + 1:
        key = hashlib.sha1(
            "\n".join(text for _, text in a[i : i + MIN_RUN]).encode()
        ).hexdigest()
        hits = index.get(key)
        if not hits:
            i += 1
            continue
        j = hits[0]
        n = MIN_RUN
        while i + n < len(a) and j + n < len(b) and a[i + n][1] == b[j + n][1]:
            n += 1
        runs.append(
            Run(
                lines=n,
                left="",
                left_start=a[i][0],
                left_end=a[i + n - 1][0],
                right="",
                right_start=b[j][0],
                right_end=b[j + n - 1][0],
            )
        )
        i += n
    return runs


def window_hashes(lines: list[tuple[int, str]]) -> set[str]:
    return {
        hashlib.sha1(
            "\n".join(text for _, text in lines[i : i + MIN_RUN]).encode()
        ).hexdigest()
        for i in range(len(lines) - MIN_RUN + 1)
    }


def candidate_pairs(
    files: list[Path], lines: dict[Path, list[tuple[int, str]]]
) -> set[tuple[Path, Path]]:
    by_hash: dict[str, list[Path]] = defaultdict(list)
    for path in files:
        for h in window_hashes(lines[path]):
            by_hash[h].append(path)
    pairs: set[tuple[Path, Path]] = set()
    for sharers in by_hash.values():
        if len(sharers) < 2:
            continue
        for x in range(len(sharers)):
            for y in range(x + 1, len(sharers)):
                a, b = sorted((sharers[x], sharers[y]))
                pairs.add((a, b))
    return pairs


def collect(addon: str = DEFAULT_ADDON) -> list[Run]:
    src = addon_src(addon)
    files = js_files(src)
    if not files:
        raise RuntimeError(
            f"no .js files under {src} — refusing to report zero duplication for "
            f"a tree that was never scanned. A ratchet that reads 0 from a bad "
            f"path banks a floor nothing can ever exceed."
        )
    lines = {p: significant(p) for p in files}
    found: list[Run] = []
    for left, right in sorted(candidate_pairs(files, lines)):
        found.extend(
            Run(
                lines=run.lines,
                left=str(left.relative_to(ROOT)),
                left_start=run.left_start,
                left_end=run.left_end,
                right=str(right.relative_to(ROOT)),
                right_start=run.right_start,
                right_end=run.right_end,
            )
            for run in maximal_runs(lines[left], lines[right])
        )
    return sorted(found, key=lambda r: (-r.lines, r.left, r.left_start))


def total(runs: list[Run]) -> int:
    return sum(r.lines for r in runs)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", action="store_true", help="print the total only")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--top", type=int, default=15, help="runs to list (0 = all)")
    parser.add_argument(
        "--addon",
        choices=GOVERNED_ADDONS,
        default=DEFAULT_ADDON,
        help="which addon's static/src to measure",
    )
    args = parser.parse_args()

    runs = collect(args.addon)
    if args.count:
        print(total(runs))
        return 0
    if args.json:
        print(json.dumps([asdict(r) for r in runs], indent=2))
        return 0

    src = addon_src(args.addon).relative_to(ROOT)
    print(f"JS duplication (byte-exact runs >= {MIN_RUN} significant lines, {src})")
    print("=" * 72)
    shown = runs if args.top == 0 else runs[: args.top]
    for run in shown:
        print(f"  {run.lines:5d}  {run.left}:{run.left_start}-{run.left_end}")
        print(f"         == {run.right}:{run.right_start}-{run.right_end}")
    if args.top and len(runs) > args.top:
        print(f"  ... and {len(runs) - args.top} more (--top 0 for all)")
    print("-" * 72)
    print(f"\n{total(runs)} duplicated significant line(s) in {len(runs)} run(s)")
    print("\nRatchet this number:")
    print("  python tooling/architecture/js_duplication.py --count \\")
    print("      | xargs python tooling/ratchet/ratchet.py jsduplication --count")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

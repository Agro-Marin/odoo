#!/usr/bin/env python3
"""A license notice that lives inline in source must not disappear.

Vendored code usually ships its license as a standalone `LICENSE` file, which no
source transformation can touch. A handful of files instead carry the notice as a
comment at the top of the source itself, and those are reachable by anything that
edits comments mechanically -- a strip, a reformat, a codemod.

That is not hypothetical. `960e4d4414d`, a comment strip whose own body said it
was comment-only, removed 81 lines from
`point_of_sale/static/src/app/utils/html-to-image.js`, among them two complete
MIT notices and the steps for regenerating the vendored file. The removed text
contains the clause that forbids removing it:

    The above copyright notice and this permission notice shall be included in
    all copies or substantial portions of the Software.

Nothing caught it. Every comparator was sound, eslint and prettier were clean,
the tests passed, and byte-identical minification -- the usual proof that a strip
moved only comments -- passes by construction, because a license notice IS a
comment. It was restored by hand in `f04ea4bd823` after a person read a diff.

THIS IS THE ONLY GATE HERE WHOSE SUBJECT IS NOT THE CODEBASE. Everything else
`tooling/architecture/` measures is ours to decide; this one is a term of the
licence the code is used under.

The check is deliberately narrow: it pins the files known to carry an inline
notice and the number of licence markers each one holds, and fails when a count
DROPS. It does not care about new files, formatting, or where in the file the
notice sits -- only that a notice which was there is still there. A hard zero,
because there is no acceptable number of removed licence notices.

Standalone `LICENSE`, `COPYING` and `*-ofl.txt` files are excluded: a licence
file cannot be damaged by a comment transformation, so pinning it would add
noise without adding protection.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

ROOT = find_odoo_root(Path(__file__).resolve(), tool="license_notices")

# One marker per distinct notice. "Permission is hereby granted" opens the MIT
# grant and appears once per MIT licence; the Apache line opens that one.
MARKERS = (
    "Permission is hereby granted",
    "Licensed under the Apache License",
)

# path relative to the odoo checkout -> number of notices it carries
PINNED: dict[str, int] = {
    "addons/point_of_sale/static/src/app/utils/html-to-image.js": 2,
    "addons/website/static/src/libs/zoomodoo/zoomodoo.js": 1,
    "addons/html_editor/static/src/main/media/image_transformation.js": 1,
    "addons/phone_validation/lib/phonenumbers_patch/__init__.py": 1,
}


@dataclass(frozen=True)
class Finding:
    path: str
    expected: int
    found: int

    def __str__(self) -> str:
        if self.found < 0:
            return f"  {self.path}  FILE GONE (expected {self.expected} notice(s))"
        return f"  {self.path}  {self.found} notice(s), expected {self.expected}"


def count_notices(text: str) -> int:
    return sum(text.count(marker) for marker in MARKERS)


def measure(root: Path = ROOT) -> list[Finding]:
    findings = []
    for rel, expected in sorted(PINNED.items()):
        path = root / rel
        if not path.is_file():
            findings.append(Finding(rel, expected, -1))
            continue
        found = count_notices(path.read_text(encoding="utf8", errors="replace"))
        if found < expected:
            findings.append(Finding(rel, expected, found))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail on any loss")
    parser.add_argument("--count", action="store_true", help="print the count only")
    parser.add_argument("--json", action="store_true", help="machine-readable")
    args = parser.parse_args(argv)

    if not PINNED:
        print(
            "error: nothing is pinned -- this gate would pass over anything",
            file=sys.stderr,
        )
        return 2
    missing = [rel for rel in PINNED if not (ROOT / rel).is_file()]
    if len(missing) == len(PINNED):
        print(
            f"error: none of the {len(PINNED)} pinned files exists under {ROOT} -- "
            f"the scan found nothing, which is not the same as finding nothing wrong",
            file=sys.stderr,
        )
        return 2

    found = measure()
    if args.count:
        print(len(found))
        return 0
    if args.json:
        print(json.dumps([asdict(f) for f in found], indent=2))
        return 0

    print("Inline license notices (hard zero)")
    print("=" * 72)
    for item in found:
        print(item)
    print("-" * 72)
    if found:
        print(f"{len(found)} file(s) lost a license notice.")
        print(
            "\nThis is not a style finding. The MIT and Apache texts both require "
            "the notice\nbe retained; restore it rather than re-pinning the count."
        )
        return 1 if args.check else 0
    total = sum(PINNED.values())
    print(f"All {total} inline notice(s) across {len(PINNED)} file(s) intact. ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

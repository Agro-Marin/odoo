"""A component directory imported from outside ``web`` has a face.

``js_face_boundary`` refuses an import that reaches *past* a face — a ``foo.js``
beside ``foo/`` re-exporting what the directory offers. It says nothing about
which directories should have one, because a face is discovered rather than
declared: the gate globs for the pairing and enforces entry wherever it finds
it. This gate answers the prior question for ``components/``.

THE SPLIT IS CLOSED
-------------------

It used to be a split, and it was never a rule. Some directories carried a face
and some did not, while being imported from outside ``web`` the same way, and
every one of them — faced or not — was reached through **exactly one** module
from outside. ``color_picker`` was reached through two and had no face, which is
the combination a "more than one consumer module" rule would predict least.
History, then, not design, and a new component's author had no rule to apply.
See ADR-0047.

Every faceless directory has since been migrated, so ``PINNED_FACELESS`` is
empty and the rule below is now the whole rule: reached from outside, therefore
faced. The pin stays because the gate is shrink-only in both directions, and an
empty frozenset is what "no debt" looks like — not something to delete, or the
next regression has nothing to fail against.

WHAT IS COUNTED
---------------

A directory directly under ``components/`` is *required* to have a face once any
module outside ``addons/web/static`` imports something under it. A directory only
``web`` itself imports is not: the reason for a face is the boundary, and there
is no outside entry to constrain.

USAGE
-----

  python js_component_face.py            # report
  python js_component_face.py --check    # gate
  python js_component_face.py --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from js_layer_check import ROOT

ADR = "0047"

WEB_STATIC = ROOT / "addons" / "web" / "static"
COMPONENTS = WEB_STATIC / "src" / "components"

CONSUMER_ROOTS = (
    ROOT / "addons",
    ROOT.parent / "enterprise",
    ROOT.parent / "agromarin",
    ROOT.parent / "design-themes",
)

SPECIFIER = re.compile(r"""["']@web/components/(?P<rest>[^"']+)["']""")

# Directories reached from outside `web` with no face. Debt, one entry per
# directory, each costing a face module and its consumers' imports. ADR-0047.
# Empty: the seventeen that were here were migrated in one pass, because each
# was reached through a single inner module and the rewrite was therefore
# mechanical -- the faces re-export exactly the names the outside was already
# importing, and `named_export_coherence` checks that they still name the same
# things.
PINNED_FACELESS: frozenset[str] = frozenset()


def has_face(directory: str, components: Path | None = None) -> bool:
    """A face is `foo.js` beside `foo/` — the same pairing js_face_boundary globs for."""
    components = COMPONENTS if components is None else components
    return (components / f"{directory}.js").is_file()


def reached_from_outside(consumer_roots=None) -> tuple[set[str], int]:
    """Component directories any module outside `addons/web/static` imports.

    `consumer_roots` resolves at CALL time, not at definition: bound as a
    default it would capture the module constant at import and no caller — a
    test included — could substitute anything for it.
    """
    consumer_roots = CONSUMER_ROOTS if consumer_roots is None else consumer_roots
    reached: set[str] = set()
    scanned = 0
    for root in consumer_roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*.js"):
            text = str(path)
            if "/addons/web/static/" in text or "node_modules" in text:
                continue
            scanned += 1
            try:
                source = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for match in SPECIFIER.finditer(source):
                rest = match.group("rest").split("/")
                # `@web/components/foo` is the face itself; `@web/components/foo/bar`
                # names the directory in its first segment either way.
                reached.add(rest[0].removesuffix(".js"))
    return reached, scanned


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit 1 on drift")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if not COMPONENTS.is_dir():
        print(f"error: {COMPONENTS} is not a directory", file=sys.stderr)
        return 2

    reached, scanned = reached_from_outside()
    if not scanned:
        print("error: no consumer JS scanned — the sweep is broken", file=sys.stderr)
        return 2

    faceless = {d for d in reached if not has_face(d)}
    new = sorted(faceless - PINNED_FACELESS)
    faced_now = sorted(PINNED_FACELESS - faceless)

    if args.json:
        print(
            json.dumps(
                {
                    "reached": sorted(reached),
                    "faceless": sorted(faceless),
                    "new": new,
                    "faced_now": faced_now,
                },
                indent=2,
            )
        )
        return 1 if ((new or faced_now) and args.check) else 0

    print("Component face coverage (pinned, shrink-only)")
    print("=" * 64)
    print(
        f"{len(reached)} directory/ies reached from outside web; "
        f"{len(reached) - len(faceless)} faced, {len(faceless)} not"
    )
    print()
    for directory in sorted(reached):
        mark = "face" if has_face(directory) else "    "
        flag = "  NEW" if directory in new else ""
        print(f"  [{mark}] {directory}{flag}")
    print("-" * 64)
    if new:
        print(
            f"\n[FAIL] {len(new)} directory/ies reached from outside web with no face:"
        )
        for directory in new:
            print(f"    components/{directory}")
        print(
            "\nAdd components/<name>.js re-exporting what the directory offers, "
            "and\nhave the outside consumers enter there — see ADR-0047. A face "
            "lets the\ndirectory move a file without touching three repositories."
        )
    if faced_now:
        print(
            f"\n[FAIL] {len(faced_now)} pinned directory/ies now have a face — unpin them:"
        )
        for directory in faced_now:
            print(f"    components/{directory}")
        print("\nThe list is shrink-only in both directions, so a migration")
        print("leaves the pin in the same commit and cannot be banked twice.")
    if not new and not faced_now:
        print("\nFace coverage unchanged. ✓")

    print(f"\nConsumer files scanned: {scanned}")
    return 1 if ((new or faced_now) and args.check) else 0


if __name__ == "__main__":
    sys.exit(main())

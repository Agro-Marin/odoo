"""A test naming an icon class that neither FontAwesome nor any source declares is red or vacuous, never right.

The FontAwesome 7 upgrade renamed icons in templates and not in the tests
that select them. room lost eighteen of twenty-two tests to
`fa-calendar-times-o`, `fa-calendar-plus-o` and `fa-trash`; website_knowledge
two to `fa-globe`; account's annotation tour negated `.fa-commenting` and so
could not fail. None of it was visible: a one-count assertion on a missing
class reads as a defect in the feature, and a negated one reads as a pass.

FontAwesome 7's own stylesheet declares every class it knows, the canonical
names and their aliases alike, so the set of icon classes a test may name
is exact: those, plus any `fa-*` a non-test source under the scanned
repositories writes (the picker's generated names, an addon's own icons).
A test naming anything else is held at zero. Comments are stripped first,
since a test may explain the class it stopped using; a deliberate
non-icon carries its reason in EXEMPT.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from js_imports import strip_comments
from js_layer_check import ROOT

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import SIBLING_REPOS

FONTAWESOME_CSS = ROOT / "addons" / "web" / "static" / "src" / "libs"
SCAN_ROOTS = (
    ROOT / "addons",
    ROOT / "odoo" / "addons",
    *(ROOT.parent / name for name in SIBLING_REPOS),
)
ICON = re.compile(r"\bfa-[a-z0-9]+(?:-[a-z0-9]+)*")
# Style, size and animation classes: not icons, and not declared as such.
NOT_ICONS = frozenset(
    {
        "fa-solid",
        "fa-regular",
        "fa-brands",
        "fa-light",
        "fa-thin",
        "fa-duotone",
        "fa-sharp",
        "fa-fw",
        "fa-spin",
        "fa-pulse",
        "fa-stack",
        "fa-inverse",
        "fa-1x",
        "fa-2x",
        "fa-3x",
        "fa-4x",
        "fa-5x",
        "fa-lg",
        "fa-sm",
        "fa-xs",
        "fa-rotate-90",
        "fa-rotate-180",
        "fa-rotate-270",
        "fa-flip-horizontal",
        "fa-flip-vertical",
    }
)
# A class a test names on purpose because it is NOT an icon, with the reason.
EXEMPT: dict[str, str] = {
    "fa-definitely-not-an-icon": (
        "web's bootstrap suite asserts that an unknown fa-* class renders nothing"
    ),
}
SOURCE_SUFFIXES = (".xml", ".js", ".py", ".scss", ".css")


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _is_test(path: Path) -> bool:
    return "/tests/" in path.as_posix()


def declared_icons(scan_roots=SCAN_ROOTS, fontawesome=FONTAWESOME_CSS) -> set[str]:
    names: set[str] = set()
    for css in fontawesome.rglob("*.css"):
        names.update(ICON.findall(_read(css)))
    for root in scan_roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.suffix not in SOURCE_SUFFIXES or "node_modules" in path.parts:
                continue
            if _is_test(path):
                continue
            names.update(ICON.findall(_read(path)))
    return names


def dead_icons(scan_roots=SCAN_ROOTS, declared: set[str] | None = None):
    """{icon class: sorted test files naming it} for classes nothing declares."""
    declared = declared_icons(scan_roots) if declared is None else declared
    found: dict[str, set[str]] = {}
    for root in scan_roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*.js"):
            if "node_modules" in path.parts or not _is_test(path):
                continue
            text = strip_comments(_read(path))
            for name in set(ICON.findall(text)):
                if name in declared or name in NOT_ICONS or name in EXEMPT:
                    continue
                found.setdefault(name, set()).add(path.relative_to(root).as_posix())
    return {k: sorted(v) for k, v in sorted(found.items())}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="exit 1 on any dead class")
    args = parser.parse_args(argv)

    declared = declared_icons()
    if len(declared) < 1000:
        print(
            f"error: only {len(declared)} icon classes declared; the stylesheet was "
            "not reached, refusing to report",
            file=sys.stderr,
        )
        return 2
    dead = dead_icons(declared=declared)
    print(f"icon classes declared: {len(declared)}")
    print(f"dead icon classes named by tests: {len(dead)}")
    for name, files in dead.items():
        print(f"  {name}")
        for f in files:
            print(f"      {f}")
    if args.check and dead:
        print(
            "[FAIL] a test names an icon class FontAwesome 7 does not declare and no "
            "source writes; rename it to what the template renders, or add it to "
            "EXEMPT with its reason",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Every shadow root must be attached through ``attachShadowRoot``.

A shadow root is invisible to a selector: there is no ``:has-shadow-root``, and
no event fires when one is attached, so the only way to *discover* a host is to
walk every element and read ``.shadowRoot``.  Measured on an 8000-element form
that scan costs about +40% on ``getTabableElements``, which runs on the
focus-trap path once per Tab keypress -- too much to pay on every page so that a
handful of them can be traversed correctly.

``attachShadowRoot`` moves the cost to attach time, where there is exactly one
host, by marking it with an attribute the traversal can select.  A raw
``attachShadow`` skips the mark, and everything that has to cross the boundary
-- tab order today, whatever needs it next -- then silently steps over the tree
it creates.  Silently is the problem: nothing fails, the content is simply not
there.

Drift-zero: there is no tolerated list, because there are three shadow roots in
the whole workspace and each one is a deliberate architectural choice.  Tests
are not scanned; a test that attaches a raw shadow root to prove the traversal
ignores it is asserting this rule, not breaking it.
"""

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from js_import_resolution import EXCLUDED_PARTS, addon_static_dirs
from js_layer_check import ROOT

ADR = "0069"

ATTACH_SHADOW = re.compile(r"\.\s*attachShadow\s*\(")

#: The helper itself is where the one real call lives.
HELPER = "addons/web/static/src/core/utils/dom/ui.js"


def _rel(path: Path, root: Path) -> str:
    return (
        path.relative_to(root).as_posix()
        if path.is_relative_to(root)
        else path.as_posix()
    )


@dataclass(frozen=True)
class RawAttach:
    file: str
    line: int

    def __str__(self) -> str:
        return (
            f"  {self.file}:{self.line}\n"
            f"      attaches a shadow root without marking its host — "
            f"the tree it creates is unreachable to every root-crossing helper"
        )


def find_raw_attachments(
    statics: dict[str, Path] | None = None,
    root: Path = ROOT,
    helper: str = HELPER,
) -> tuple[list[RawAttach], int]:
    statics = addon_static_dirs() if statics is None else statics
    findings: list[RawAttach] = []
    scanned = 0
    for _addon, static in sorted(statics.items()):
        src = static / "src"
        if not src.is_dir():
            continue
        for path in sorted(src.rglob("*.js")):
            if EXCLUDED_PARTS.intersection(path.relative_to(src).parts):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError) as exc:  # pragma: no cover
                print(f"warning: could not read {path}: {exc}", file=sys.stderr)
                continue
            scanned += 1
            if "attachShadow" not in text:
                continue
            rel = _rel(path, root)
            if rel == helper:
                continue
            findings.extend(
                RawAttach(file=rel, line=text.count("\n", 0, match.start()) + 1)
                for match in ATTACH_SHADOW.finditer(text)
            )
    return findings, scanned


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit 1 on findings")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    findings, n_files = find_raw_attachments()

    if not n_files:
        print(
            "error: no addon static/src trees found under the checkout", file=sys.stderr
        )
        return 2

    if args.json:
        print(json.dumps([asdict(f) for f in findings], indent=2))
    else:
        print("JS shadow-root attachment check (drift-zero, no tolerated list)")
        print("=" * 64)
        for finding in findings:
            print(finding)
        print("-" * 64)
        if findings:
            print(f"\n{len(findings)} raw attachShadow call(s).")
            print("Attach through `attachShadowRoot` from @web/core/utils/dom/ui")
            print("so the host carries the mark that makes it findable by a")
            print("selector. Without it the shadow tree is skipped in silence:")
            print("nothing fails, the content is simply not there.")
        else:
            print("\nEvery shadow root is attached through the helper. ✓")
        print(f"\nFiles scanned: {n_files}")

    return 1 if (findings and args.check) else 0


if __name__ == "__main__":
    sys.exit(main())

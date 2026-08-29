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
    parser = argparse.ArgumentParser()
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

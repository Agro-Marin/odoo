import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from js_import_resolution import EXCLUDED_PARTS, addon_static_dirs
from js_layer_check import ROOT

ADR = "0027"

FORCED_RENDER = re.compile(r"\.\s*render\s*\(\s*true\s*\)")

WEB_ADDON = "web"


@dataclass(frozen=True)
class KnownForced:
    file: str
    reason: str


KNOWN_FORCED: tuple[KnownForced, ...] = (
    KnownForced(
        file="addons/web/static/src/fields/relational/x2many_dialog.js",
        reason=(
            "`saveAndNew()` assigns `this.title`, a plain instance property that "
            "nothing subscribes to, and then reuses the dialog for a DIFFERENT "
            "record. The force is publishing an unreactive mutation and resetting "
            "a subtree for new content, which is what it is for. The bus listener "
            "in the same file — the per-dialog copy of the old blanket — was "
            "un-forced; this one is not that."
        ),
    ),
)


def _rel(path: Path, root: Path) -> str:
    return (
        path.relative_to(root).as_posix()
        if path.is_relative_to(root)
        else path.as_posix()
    )


@dataclass(frozen=True)
class ForcedRender:
    file: str
    line: int

    def __str__(self) -> str:
        return (
            f"  {self.file}:{self.line}\n"
            f"      forces a subtree render — use `render()`, or pin it in "
            f"KNOWN_FORCED with a reason"
        )


def find_forced_renders(
    statics: dict[str, Path] | None = None, root: Path = ROOT
) -> tuple[list[ForcedRender], int, int]:

    statics = addon_static_dirs() if statics is None else statics
    pinned = {k.file for k in KNOWN_FORCED}
    findings: list[ForcedRender] = []
    scanned = 0
    elsewhere = 0
    for addon, static in sorted(statics.items()):
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
            if addon == WEB_ADDON:
                scanned += 1
            if "render" not in text:
                continue
            rel = _rel(path, root)
            for match in FORCED_RENDER.finditer(text):
                if addon != WEB_ADDON:
                    elsewhere += 1
                    continue
                if rel in pinned:
                    continue
                findings.append(
                    ForcedRender(file=rel, line=text.count("\n", 0, match.start()) + 1)
                )
    return findings, scanned, elsewhere


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit 1 on findings")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--count",
        action="store_true",
        help="print the forced-render count OUTSIDE web core, for the ratchet",
    )
    args = parser.parse_args(argv)

    findings, n_files, n_elsewhere = find_forced_renders()

    if not n_files:
        print("error: no web/static/src tree found under the checkout", file=sys.stderr)
        return 2

    if args.count:
        print(n_elsewhere)
        return 0

    if args.json:
        print(json.dumps([asdict(f) for f in findings], indent=2))
    else:
        print("JS forced-render check (web core; pinned sites carry a reason)")
        print("=" * 64)
        for finding in findings:
            print(finding)
        print("-" * 64)
        if findings:
            print(f"\n{len(findings)} unpinned forced render(s) in web core.")
            print("A forced render re-renders the whole subtree unconditionally,")
            print("defeats `t-props` diffing, and hides reads that subscribe to")
            print("nothing. Prefer `render()`; subscribe what the component reads.")
        else:
            print("\nNo unpinned forced render in web core. ✓")
        for known in KNOWN_FORCED:
            print(f"\npinned: {known.file}\n    {known.reason}")
        print(
            f"\nWeb files scanned: {n_files}   "
            f"forced renders in other addons (not faulted): {n_elsewhere}"
        )

    return 1 if (findings and args.check) else 0


if __name__ == "__main__":
    sys.exit(main())

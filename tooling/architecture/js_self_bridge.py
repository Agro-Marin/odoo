import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from js_import_resolution import EXCLUDED_PARTS, addon_static_dirs
from js_layer_check import ROOT

ADR = "0026"

BRIDGE_CALL = re.compile(
    r"""odoo\s*\.\s*loader\s*\.\s*modules\s*\.\s*get\s*\(\s*(['"])(?P<spec>[^'"]+)\1"""
)


def _rel(path: Path, root: Path) -> str:
    return (
        path.relative_to(root).as_posix()
        if path.is_relative_to(root)
        else path.as_posix()
    )


@dataclass(frozen=True)
class SelfBridge:
    file: str
    line: int
    specifier: str

    def __str__(self) -> str:
        return (
            f"  {self.file}:{self.line}\n"
            f"      resolves its own specifier {self.specifier} — "
            f"every export is undefined"
        )


def own_specifiers(path: Path, addon: str, static: Path) -> set[str]:

    stem = path.relative_to(static / "src").as_posix().removesuffix(".js")
    specs = {f"@{addon}/{stem}"}
    if stem.endswith("/index"):
        specs.add(f"@{addon}/{stem.removesuffix('/index')}")
    return specs


def find_self_bridges(
    statics: dict[str, Path] | None = None, root: Path = ROOT
) -> tuple[list[SelfBridge], int, int]:

    statics = addon_static_dirs() if statics is None else statics
    findings: list[SelfBridge] = []
    scanned = 0
    reads = 0
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
            scanned += 1
            if "loader" not in text:
                continue
            mine = own_specifiers(path, addon, static)
            for match in BRIDGE_CALL.finditer(text):
                reads += 1
                spec = match.group("spec").removesuffix(".js")
                if spec in mine:
                    findings.append(
                        SelfBridge(
                            file=_rel(path, root),
                            line=text.count("\n", 0, match.start()) + 1,
                            specifier=spec,
                        )
                    )
    return findings, scanned, reads


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit 1 on findings")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    findings, n_files, n_reads = find_self_bridges()

    if not n_files:
        print(
            "error: no addon static/src trees found under the checkout", file=sys.stderr
        )
        return 2

    if args.json:
        print(json.dumps([asdict(f) for f in findings], indent=2))
    else:
        print("JS self-bridge check (drift-zero, no tolerated list)")
        print("=" * 64)
        for finding in findings:
            print(finding)
        print("-" * 64)
        if findings:
            print(f"\n{len(findings)} module(s) bridged to themselves.")
            print("A generated bridge was written over the source it came from:")
            print("the module resolves itself, so every export it names is")
            print("undefined. Restore the implementation from git.")
        else:
            print("\nNo module resolves itself through the loader. ✓")
        print(f"\nFiles scanned: {n_files}   literal loader reads: {n_reads}")

    return 1 if (findings and args.check) else 0


if __name__ == "__main__":
    sys.exit(main())

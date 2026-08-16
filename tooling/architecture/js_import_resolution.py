import argparse
import json
import posixpath
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from js_imports import collect_imports
from js_layer_check import ROOT

ADR = "0023"

ADDON_ROOTS: tuple[Path, ...] = (ROOT / "addons", ROOT / "odoo" / "addons")

EXCLUDED_PARTS = frozenset({"lib", "legacy", "__pycache__", "node_modules"})

SCANNED_SUBTREES = ("src", "tests")


def _rel(path: Path, root: Path) -> str:
    return (
        path.relative_to(root).as_posix()
        if path.is_relative_to(root)
        else path.as_posix()
    )


@dataclass(frozen=True)
class Unresolved:
    file: str
    line: int
    specifier: str
    tried: str

    def __str__(self) -> str:
        return f"  {self.file}:{self.line}\n      {self.specifier}  ->  {self.tried} (missing)"


def addon_static_dirs() -> dict[str, Path]:

    dirs: dict[str, Path] = {}
    for root in ADDON_ROOTS:
        if not root.is_dir():
            continue
        for addon in sorted(root.iterdir()):
            static = addon / "static"
            if static.is_dir() and addon.name not in dirs:
                dirs[addon.name] = static
    return dirs


def iter_source_files(statics: dict[str, Path]) -> list[tuple[str, Path]]:
    out: list[tuple[str, Path]] = []
    for addon, static in statics.items():
        for sub in SCANNED_SUBTREES:
            base = static / sub
            if not base.is_dir():
                continue
            for path in sorted(base.rglob("*.js")):
                if EXCLUDED_PARTS.intersection(path.relative_to(base).parts):
                    continue
                out.append((addon, path))
    return out


def resolve_target(
    spec: str, path: Path, addon: str, statics: dict[str, Path]
) -> Path | None:

    if spec.startswith("."):
        return Path(posixpath.normpath(posixpath.join(path.parent.as_posix(), spec)))
    if not spec.startswith("@"):
        return None
    owner, _, rest = spec[1:].partition("/")
    if not rest:
        return None
    static = statics.get(owner)
    if static is None:
        return None
    if rest.startswith("../"):
        return static / rest[3:]
    return static / "src" / rest


def exists(target: Path) -> bool:
    return (
        target.is_file()
        or target.with_name(target.name + ".js").is_file()
        or (target / "index.js").is_file()
    )


def find_unresolved(
    statics: dict[str, Path] | None = None, root: Path = ROOT
) -> tuple[list[Unresolved], int, int]:

    statics = addon_static_dirs() if statics is None else statics
    findings: list[Unresolved] = []
    files = iter_source_files(statics)
    checked = 0
    for addon, path in files:
        try:
            src = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as exc:  # pragma: no cover
            print(f"warning: could not read {path}: {exc}", file=sys.stderr)
            continue
        for spec, lineno in collect_imports(src):
            target = resolve_target(spec, path, addon, statics)
            if target is None:
                continue
            checked += 1
            if not exists(target):
                findings.append(
                    Unresolved(
                        file=_rel(path, root),
                        line=lineno,
                        specifier=spec,
                        tried=_rel(target, root),
                    )
                )
    return findings, len(files), checked


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit 1 on findings")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    findings, n_files, n_specs = find_unresolved()

    if not n_files:
        print(
            f"error: no addon static trees found under {ADDON_ROOTS}", file=sys.stderr
        )
        return 2

    if args.json:
        print(json.dumps([asdict(f) for f in findings], indent=2))
    else:
        print("JS import-resolution check (drift-zero, no tolerated list)")
        print("=" * 64)
        for finding in findings:
            print(finding)
        print("-" * 64)
        if findings:
            print(f"\n{len(findings)} unresolvable first-party specifier(s).")
            print("An unresolvable specifier means the module never evaluates:")
            print("a test suite registers 0 tests and still exits 0.")
        else:
            print("\nEvery first-party specifier resolves. ✓")
        print(f"\nFiles scanned: {n_files}   specifiers checked: {n_specs}")

    return 1 if (findings and args.check) else 0


if __name__ == "__main__":
    sys.exit(main())

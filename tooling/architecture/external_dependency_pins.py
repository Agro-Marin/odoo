import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

ADR = "unrecorded"

ROOT = find_odoo_root(Path(__file__).resolve(), tool="external_dependency_pins")

SCAN_ROOTS = ("addons", "odoo/addons")

CORE_REQUIREMENTS = "requirements.txt"

ADDON_REQUIREMENTS = "requirements-addons.txt"

_NAME = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)")


def _normalise(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _requirement_name(spec: str) -> str:
    match = _NAME.match(spec.strip())
    return _normalise(match.group(1)) if match else ""


def read_pins(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    names = set()
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "-")):
            continue
        name = _requirement_name(line)
        if name:
            names.add(name)
    return names


@dataclass(frozen=True)
class Finding:
    module: str
    path: str
    dependency: str
    searched: tuple[str, ...]
    suggestion: str | None = field(default=None)

    def __str__(self) -> str:
        where = ", ".join(self.searched)
        hint = f" -- did you mean {self.suggestion}?" if self.suggestion else ""
        return (
            f"{self.path}  {self.module} declares {self.dependency!r}, "
            f"pinned in none of: {where}{hint}"
        )


def _manifests(root: Path):
    for path in sorted(root.rglob("__manifest__.py")):
        if "node_modules" in path.parts:
            continue
        try:
            manifest = ast.literal_eval(path.read_text(encoding="utf-8"))
        except SyntaxError, ValueError:
            continue
        if isinstance(manifest, dict):
            yield path, manifest


def _declared(manifest: dict) -> list[str]:
    external = manifest.get("external_dependencies")
    if not isinstance(external, dict):
        return []
    declared = external.get("python")
    return [d for d in declared if isinstance(d, str)] if declared else []


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _suggest(dependency: str, pins: set[str]) -> str | None:
    target = _normalise(dependency)
    for pinned in sorted(pins):
        parts = pinned.split("-")
        if target != pinned and target in parts and len(parts) > 1:
            return pinned
    return None


def pin_sources(tree: Path) -> list[Path]:
    if tree == ROOT or tree.is_relative_to(ROOT):
        return [ROOT / CORE_REQUIREMENTS, ROOT / ADDON_REQUIREMENTS]
    return [tree / CORE_REQUIREMENTS, ROOT / CORE_REQUIREMENTS]


def measure(roots: list[Path] | None = None) -> list[Finding]:
    trees = roots or [ROOT / r for r in SCAN_ROOTS]

    seen_manifests = 0
    seen_declarations = 0
    findings: list[Finding] = []
    for tree in trees:
        sources = pin_sources(tree)
        pins: set[str] = set()
        for source in sources:
            pins |= read_pins(source)
        searched = tuple(_rel(s) for s in sources)
        for path, manifest in _manifests(tree):
            seen_manifests += 1
            for dependency in _declared(manifest):
                seen_declarations += 1
                if _requirement_name(dependency) in pins:
                    continue
                findings.append(
                    Finding(
                        module=path.parent.name,
                        path=_rel(path),
                        dependency=dependency,
                        searched=searched,
                        suggestion=_suggest(dependency, pins),
                    )
                )

    if not seen_manifests:
        raise SystemExit(
            f"external_dependency_pins: no __manifest__.py under "
            f"{', '.join(_rel(t) for t in trees)} — the scan found no inputs; "
            "refusing to report 0 findings."
        )
    if not seen_declarations:
        raise SystemExit(
            f"external_dependency_pins: the {seen_manifests} manifest(s) under "
            f"{', '.join(_rel(t) for t in trees)} declare no Python dependency "
            "at all; the scan read nothing, so 0 findings would be vacuous."
        )
    return sorted(findings, key=lambda f: (f.path, f.dependency))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check", action="store_true", help="CI mode: exit 1 on any finding"
    )
    parser.add_argument("--count", action="store_true", help="print the count only")
    parser.add_argument("--json", action="store_true", help="machine-readable")
    parser.add_argument("--roots", nargs="+", help="extra repos to scan for manifests")
    args = parser.parse_args(argv)

    roots = [ROOT / r for r in SCAN_ROOTS]
    if args.roots:
        roots += [Path(r).resolve() for r in args.roots]
    findings = measure(roots)

    if args.count:
        print(len(findings))
        return 0
    if args.json:
        print(json.dumps([f.__dict__ for f in findings], indent=2, default=list))
        return 1 if (args.check and findings) else 0

    print("external dependency pins")
    print("=" * 72)
    for finding in findings:
        print(f"  {finding}")
    if not findings:
        print("  every declared Python dependency is pinned by its own repo. ✓")
    print("-" * 72)
    print(f"scanned: {', '.join(_rel(r) for r in roots)}")
    print(f"findings: {len(findings)}")
    if findings:
        print(
            "\nEach one is a module that installs here only because something\n"
            "else dragged the package in. Add the pin to the requirements file\n"
            "of the repo that owns the module."
        )
    return 1 if (args.check and findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())

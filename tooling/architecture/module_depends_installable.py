from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _repo_root import find_odoo_root

ADR = "0062"

ROOT = find_odoo_root(Path(__file__).resolve(), tool="module_depends_installable")

MANIFEST = "__manifest__.py"


@dataclass(frozen=True)
class Module:
    name: str
    path: str
    installable: bool
    depends: tuple[str, ...]


@dataclass(frozen=True)
class Offence:
    module: str
    module_path: str
    dependency: str
    dependency_path: str

    def __str__(self) -> str:
        return (
            f"{self.module_path}  depends on `{self.dependency}`, "
            f"which is marked uninstallable ({self.dependency_path})"
        )


def _read_manifest(path: Path) -> dict | None:
    try:
        value = ast.literal_eval(path.read_text(encoding="utf-8"))
    except SyntaxError, ValueError, UnicodeDecodeError:
        return None
    return value if isinstance(value, dict) else None


def collect_modules(roots: list[Path]) -> dict[str, Module]:
    modules: dict[str, Module] = {}
    for root in roots:
        for manifest in sorted(root.glob(f"*/{MANIFEST}")):
            data = _read_manifest(manifest)
            if data is None:
                continue
            directory = manifest.parent
            depends = data.get("depends") or []
            modules[directory.name] = Module(
                name=directory.name,
                path=str(directory),
                installable=bool(data.get("installable", True)),
                depends=tuple(d for d in depends if isinstance(d, str)),
            )
    return modules


def default_roots() -> list[Path]:
    return [ROOT / "addons", ROOT / "odoo" / "addons"]


def measure(roots: list[Path] | None = None) -> list[Offence]:
    roots = roots or default_roots()
    missing = [root for root in roots if not root.is_dir()]
    if missing:
        raise RuntimeError(
            "no such directory: " + ", ".join(str(root) for root in missing)
        )

    modules = collect_modules(roots)
    if not modules:
        raise RuntimeError(
            "no `__manifest__.py` under "
            + ", ".join(str(root) for root in roots)
            + " — refusing to report a result measured over nothing"
        )

    offences = [
        Offence(
            module=module.name,
            module_path=module.path,
            dependency=dependency,
            dependency_path=modules[dependency].path,
        )
        for module in modules.values()
        if module.installable
        for dependency in module.depends
        if dependency in modules and not modules[dependency].installable
    ]
    return sorted(offences, key=lambda o: (o.module_path, o.dependency))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check", action="store_true", help="exit non-zero if any offence is found"
    )
    parser.add_argument("--count", action="store_true", help="print the count only")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--roots", nargs="+", help="scan these paths instead of the odoo checkout"
    )
    args = parser.parse_args(argv)

    roots = [Path(r).resolve() for r in args.roots] if args.roots else None
    try:
        found = measure(roots)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.count:
        print(len(found))
        return 0
    if args.json:
        print(json.dumps([asdict(o) for o in found], indent=2))
        return 0

    print("Installable modules depending on an uninstallable one")
    print("=" * 72)
    for offence in found:
        print(f"  {offence}")
    if not found:
        print("  none")
    print("-" * 72)
    print(f"\n{len(found)} unreachable module(s)")
    if found:
        print(
            "\nEach of these is skipped by the module graph with a WARNING and "
            "left in\nstate `to install`, while odoo-bin exits 0. Resolve each by "
            "what it uses:\ndrop the dependency, port what it needed, or mark it "
            "uninstallable too."
        )

    if args.check and found:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

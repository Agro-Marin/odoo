"""An installable module must not depend on one the module graph cannot load.

Two questions, one scan, because both are answered from the same manifest index.

The default question is *uninstallable*: an installable module naming a
dependency marked ``installable = False``. The graph skips such a module with a
WARNING and leaves it in state `to install` while odoo-bin exits 0, so the
module's own suite never runs and nothing is red.

``--require-present`` adds the second question — a dependency no scanned root
supplies at all — and is **off by default on purpose**. Absence is only an
offence when the caller can assert the roots are the whole addons path: the
odoo lane checks this repository out alone, and `addons_data_dir` can supply a
module at runtime that no checkout carries. Pass it only from a caller that
assembles every root a deployment loads; then it is the check that a module
removed from one repository leaves no dependant naming it in another.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _repo_root import find_odoo_root

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _ast_cache

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
    value = _ast_cache.literal_file(path)
    return value if isinstance(value, dict) else None


@dataclass(frozen=True)
class Absence:
    module: str
    module_path: str
    dependency: str

    def __str__(self) -> str:
        return (
            f"{self.module_path}  depends on `{self.dependency}`, "
            f"which no scanned root supplies"
        )


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


def _load(roots: list[Path] | None) -> dict[str, Module]:
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
    return modules


def measure(roots: list[Path] | None = None) -> list[Offence]:
    modules = _load(roots)
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


def measure_absent(roots: list[Path] | None = None) -> list[Absence]:
    modules = _load(roots)
    absences = [
        Absence(
            module=module.name,
            module_path=module.path,
            dependency=dependency,
        )
        for module in modules.values()
        if module.installable
        for dependency in module.depends
        if dependency not in modules
    ]
    return sorted(absences, key=lambda a: (a.module_path, a.dependency))


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
    parser.add_argument(
        "--require-present",
        action="store_true",
        help="also report a dependency no scanned root supplies; pass it only "
        "when --roots is the whole addons path a deployment loads",
    )
    args = parser.parse_args(argv)

    roots = [Path(r).resolve() for r in args.roots] if args.roots else None
    try:
        found = measure(roots)
        absent = measure_absent(roots) if args.require_present else []
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.count:
        print(len(found) + len(absent))
        return 0
    if args.json:
        uninstallable = [asdict(o) for o in found]
        payload = (
            {"uninstallable": uninstallable, "absent": [asdict(a) for a in absent]}
            if args.require_present
            else uninstallable
        )
        print(json.dumps(payload, indent=2))
        return 0

    print("Installable modules depending on an uninstallable one")
    print("=" * 72)
    for offence in found:
        print(f"  {offence}")
    if not found:
        print("  none")
    print("-" * 72)
    print(f"\n{len(found)} unreachable module(s)")
    if args.require_present:
        print("\nInstallable modules depending on one no scanned root supplies")
        print("=" * 72)
        for absence in absent:
            print(f"  {absence}")
        if not absent:
            print("  none")
        print("-" * 72)
        print(f"\n{len(absent)} dangling dependency edge(s)")
    if found:
        print(
            "\nEach of these is skipped by the module graph with a WARNING and "
            "left in\nstate `to install`, while odoo-bin exits 0. Resolve each by "
            "what it uses:\ndrop the dependency, port what it needed, or mark it "
            "uninstallable too."
        )

    if absent:
        print(
            "\nEach of these names a module no scanned root carries. Restore the "
            "module,\ndrop the dependency, or narrow --roots to a scope that does "
            "not claim to be\nthe whole addons path."
        )

    if args.check and (found or absent):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

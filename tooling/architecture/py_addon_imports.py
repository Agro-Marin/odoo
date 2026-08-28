"""Every ``from odoo.addons.X import`` finds an X, across the checkouts (ADR-0031).

The Python twin of :mod:`named_export_coherence`, which asks the same question of
``import { x }`` and has asked it since ADR-0031. Nothing asked it of Python, and
the omission is not academic: measured 2026-08-27, **published
``agromarin/mcp_server`` imports ``odoo.addons.rpc.tools.preflight`` at module
level, and no published repository provides it.** The module cannot be imported
against the published community fork at all, so it cannot install -- and both
repositories' CI reported green, because each one only ever sees its own tree.

CROSS-REPO, AND IT HAS TO BE, for the reason its JS twin gives. A sibling
checkout imports `odoo.addons.web`, `odoo.addons.mail` and `odoo.addons.rpc`
that it does not contain, so a repo-alone run cannot resolve them. This yields
**no verdict** for an addon whose tree is absent rather than guessing one -- an
absent checkout is not a missing module -- which is why each sibling re-runs it
from its own lane with the community fork beside it.

WHAT IT DELIBERATELY DOES NOT SEE. Only the leading module path is resolved: an
attribute the module does not define is Python's to raise and is not decidable
from the import line. `if TYPE_CHECKING:` blocks are skipped, since those imports
never execute.
"""

import argparse
import ast
import json
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root, sibling_repos_root

ADR = "0031"

ROOT = find_odoo_root(Path(__file__).resolve(), tool="py_addon_imports")
SIBLING_REPOS_ROOT = sibling_repos_root(ROOT)

EXCLUDED_PARTS = frozenset({"__pycache__", "node_modules", "static", "migrations"})

# Addons that exist only while a test is running: the suite writes the package
# into a temporary addons path and installs it, so the import resolves at run
# time and to no tree on disk. Named rather than skipped by directory, because
# "it is under tests/" is also true of every real cross-addon test import, which
# is the majority of what this gate checks.
RUNTIME_FIXTURE_ADDONS = frozenset(
    {
        # odoo/http/tests/test_routing_diamond.py builds these per test.
        "rd_sides",
        "rd_ov",
        "rd_leaf",
        "rd_chain",
        # odoo/http/tests/test_routing_per_build_state.py, same shape.
        "pb_base",
    }
)

# Module prefixes assembled on a device rather than shipped in a checkout. The
# IoT box empties `iot_drivers/iot_handlers/` and re-downloads it from every
# installed module (`helpers.delete_iot_handlers`, `download_iot_handlers`), so
# a driver importing `...iot_handlers.lib.ctypes_terminal_driver` resolves there
# and in no server tree. Exempted by prefix, not by importing directory: a
# handler importing an ordinary module is still checked.
RUNTIME_ASSEMBLED_PREFIXES = ("odoo.addons.iot_drivers.iot_handlers.",)


@dataclass(frozen=True)
class Unresolved:
    file: str
    module: str

    def __str__(self) -> str:
        return f"{self.file}: imports '{self.module}', which no checkout provides"


def _addon_dirs(addons_roots: list[Path]) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for root in addons_roots:
        if not root.is_dir():
            continue
        for manifest in root.glob("*/__manifest__.py"):
            found.setdefault(manifest.parent.name, manifest.parent)
    return found


def _resolves(dotted: str, addon_dirs: dict[str, Path]) -> bool | None:
    """True/False, or None when the providing checkout is simply absent."""
    if dotted.startswith(RUNTIME_ASSEMBLED_PREFIXES):
        return None
    parts = dotted.split(".")[2:]
    if not parts:
        return None
    addon, rest = parts[0], parts[1:]
    if addon in RUNTIME_FIXTURE_ADDONS:
        return None
    directory = addon_dirs.get(addon)
    if directory is None:
        return None
    if not rest:
        return True
    target = directory.joinpath(*rest)
    # A bare directory counts: Python 3 imports a namespace package with no
    # `__init__.py`, and several addons ship one (`account_loans/lib`,
    # `ai/utils/tools_schema`). Requiring the marker file reported five
    # perfectly importable modules as missing.
    return target.with_suffix(".py").is_file() or target.is_dir()


def _imported_modules(tree: ast.AST) -> set[str]:
    """Every `odoo.addons.*` module an executed import names."""
    skipped: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and ast.dump(node.test).find("TYPE_CHECKING") >= 0:
            skipped.update(id(child) for child in ast.walk(node) if child is not node)
    modules = set()
    for node in ast.walk(tree):
        if id(node) in skipped:
            continue
        if isinstance(node, ast.Import):
            modules.update(
                a.name for a in node.names if a.name.startswith("odoo.addons.")
            )
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            if node.module.startswith("odoo.addons."):
                modules.add(node.module)
    return modules


def _scan_files(root: Path):
    for path in root.rglob("*.py"):
        if EXCLUDED_PARTS & set(path.parts):
            continue
        yield path


def find_unresolved(
    scan_roots: list[Path], addons_roots: list[Path]
) -> list[Unresolved]:
    addon_dirs = _addon_dirs(addons_roots)
    out: list[Unresolved] = []
    for root in scan_roots:
        for path in _scan_files(root):
            try:
                tree = ast.parse(path.read_text(errors="replace"))
            except SyntaxError:
                continue
            out.extend(
                Unresolved(str(path), module)
                for module in sorted(_imported_modules(tree))
                if _resolves(module, addon_dirs) is False
            )
    return sorted(out, key=lambda u: (u.file, u.module))


def discover_addons_roots() -> list[Path]:
    roots = [ROOT / "addons", ROOT / "odoo" / "addons"]
    siblings = (
        sorted(SIBLING_REPOS_ROOT.iterdir()) if SIBLING_REPOS_ROOT.is_dir() else []
    )
    roots.extend(s for s in siblings if s != ROOT and (s / ".git").exists())
    return [r for r in roots if r.is_dir()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("roots", nargs="*", type=Path, help="addons roots to SCAN")
    parser.add_argument(
        "--addons-root",
        action="append",
        type=Path,
        default=[],
        metavar="PATH",
        help="addons root used to RESOLVE modules (defaults to the scanned roots)",
    )
    parser.add_argument("--check", action="store_true", help="exit 1 on findings")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--list-roots", action="store_true")
    args = parser.parse_args(argv)

    scan_roots = args.roots or discover_addons_roots()
    if not scan_roots:
        parser.error(f"no addons root found around {ROOT}")
    addons_roots = args.addons_root or scan_roots
    if args.list_roots:
        for root in scan_roots:
            print(root)
        return 0

    if not any(True for root in scan_roots for _ in _scan_files(root)):
        parser.error(
            f"no python sources under {len(scan_roots)} scanned root(s) — "
            "the scan reached nothing"
        )

    unresolved = find_unresolved(scan_roots, addons_roots)
    if args.json:
        print(json.dumps([u.__dict__ for u in unresolved], indent=2))
    else:
        for item in unresolved:
            print(item)
        print(f"\n{len(unresolved)} unresolvable addon import(s)")
    return 1 if (unresolved and args.check) else 0


if __name__ == "__main__":
    raise SystemExit(main())

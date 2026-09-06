import argparse
import ast
import json
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root, sibling_repos_root

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _ast_cache

ROOT = find_odoo_root(Path(__file__).resolve(), tool="py_addon_imports")
SIBLING_REPOS_ROOT = sibling_repos_root(ROOT)

EXCLUDED_PARTS = frozenset(
    {"__pycache__", "node_modules", "static", "migrations", ".worktrees"}
)

RUNTIME_FIXTURE_ADDONS = frozenset(
    {
        "rd_sides",
        "rd_ov",
        "rd_leaf",
        "rd_chain",
        "pb_base",
    }
)

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
    return target.with_suffix(".py").is_file() or target.is_dir()


def _imported_modules(tree: ast.AST) -> set[str]:
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
            tree = _ast_cache.parse_file(path)
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
    # A sibling counts as an addons root when it holds addons: the knowledge
    # vault beside the checkouts is a git repository too, and its personal
    # workspaces carry Python that is not ours to parse.
    roots.extend(
        s
        for s in siblings
        if s != ROOT and (s / ".git").exists() and any(s.glob("*/__manifest__.py"))
    )
    return [r for r in roots if r.is_dir()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
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

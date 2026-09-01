#!/usr/bin/env python3

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _sources
from _repo_root import find_odoo_root

ROOT = find_odoo_root(Path(__file__).resolve(), tool="orphan_depends")
SCAN_ROOTS = ("odoo", "addons")

HOOK_KWARGS = ("compute", "inverse", "search")
DEPENDS_DECORATORS = (
    "api.depends",
    "api.depends_context",
    "depends",
    "depends_context",
)


@dataclass(frozen=True)
class Violation:
    file: str
    line: int
    method: str
    decorator: str

    def __str__(self) -> str:
        return f"{self.file}:{self.line}  {self.method}  @{self.decorator}"


def _decorator_name(node: ast.expr) -> str:
    target = node.func if isinstance(node, ast.Call) else node
    if isinstance(target, ast.Attribute):
        value = target.value
        prefix = value.id if isinstance(value, ast.Name) else ""
        return f"{prefix}.{target.attr}" if prefix else target.attr
    return getattr(target, "id", "")


def _hook_names(tree: ast.Module) -> set[str]:
    """Every name any field in this file wires as compute/inverse/search.

    Collected file-wide rather than per class: a mixin declares the field and
    the method together, but the method is also inherited onto models that
    carry no such field, and a per-model reading calls those orphans. Both
    spellings count -- ``compute="_compute_x"`` and the bare
    ``compute=_compute_x`` reference that ``res.lang.flag_image_url`` uses,
    which a string-only reading misses.
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if not isinstance(node.func.value, ast.Name) or node.func.value.id != "fields":
            continue
        for keyword in node.keywords:
            if keyword.arg not in HOOK_KWARGS:
                continue
            value = keyword.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                names.add(value.value)
            elif isinstance(value, ast.Name):
                names.add(value.id)
            elif isinstance(value, ast.Attribute):
                names.add(value.attr)
    return names


def _depends_methods(tree: ast.Module) -> list[tuple[ast.FunctionDef, str]]:
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            name = _decorator_name(decorator)
            if name in DEPENDS_DECORATORS:
                found.append((node, name))
                break
    return found


def _python_files(roots: list[Path]) -> list[Path]:
    return sorted(
        path
        for root in roots
        for path in root.rglob("*.py")
        if "__pycache__" not in path.parts and not _sources.is_test_path(path)
    )


def measure(roots: list[Path] | None = None) -> list[Violation]:
    roots = roots or [ROOT / name for name in SCAN_ROOTS]
    files = _python_files(roots)
    if not files:
        raise RuntimeError(
            f"no Python files under {', '.join(str(r) for r in roots)} — "
            f"refusing to report a count from an empty scan"
        )

    trees: dict[Path, ast.Module] = {}
    wired: set[str] = set()
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        trees[path] = tree
        wired |= _hook_names(tree)

    found = []
    for path, tree in trees.items():
        for node, decorator in _depends_methods(tree):
            if node.name in wired:
                continue
            found.append(
                Violation(
                    _sources.display_across_repos(path, ROOT),
                    node.lineno,
                    node.name,
                    decorator,
                )
            )
    return sorted(found, key=lambda v: (v.file, v.line))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="@api.depends on a method no field wires is inert."
    )
    parser.add_argument("--count", action="store_true", help="print the count only")
    parser.add_argument("--check", action="store_true", help="exit 1 on any offender")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument(
        "--roots", nargs="+", help="scan these paths instead of odoo/ and addons/"
    )
    parser.add_argument(
        "--top", type=int, default=30, help="offenders to list (0 = all)"
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
        print(json.dumps([asdict(v) for v in found], indent=2))
        return 1 if (args.check and found) else 0

    print("Methods carrying @api.depends that no field wires")
    print("=" * 72)
    shown = found if args.top == 0 else found[: args.top]
    for item in shown:
        print(f"  {item}")
    if len(found) > len(shown):
        print(f"  ... and {len(found) - len(shown)} more (--top 0 for all)")
    print("-" * 72)
    print(f"\n{len(found)} inert declaration(s)\n")
    if found:
        print("Each is a dependency list the ORM never reads: the field computed by")
        print("the method beside it is invalidated by nothing. Move the decorator")
        print("onto the method a field names, or delete it.")
    return 1 if (args.check and found) else 0


if __name__ == "__main__":
    raise SystemExit(main())

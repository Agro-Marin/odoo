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

ADR = "0058"

ROOT = find_odoo_root(Path(__file__).resolve(), tool="py_unresolved_calls")

SCOPES = (ROOT / "odoo", ROOT / "addons")

EXTERNAL: frozenset[str] = frozenset(
    {
        "_add_object",
        "_ansi_style",
        "_asdict",
        "_build_localename",
        "_create_stdlib_context",
        "_current_frames",
        "_exit",
        "_formatMessage",
        "_getframe",
        "_load_region",
    }
)


@dataclass(frozen=True)
class UnresolvedCall:
    file: str
    line: int
    name: str
    source: str

    def __str__(self) -> str:
        return f"  {self.file}:{self.line}  {self.name}\n      {self.source}"


def iter_source_files(scopes: tuple[Path, ...] = SCOPES) -> list[Path]:
    return sorted(
        p
        for scope in scopes
        for p in scope.rglob("*.py")
        if "__pycache__" not in p.parts
    )


def measure(scopes: tuple[Path, ...] = SCOPES) -> list[UnresolvedCall]:
    files = iter_source_files(scopes)
    if not files:
        raise RuntimeError(
            f"no Python sources under {', '.join(str(s) for s in scopes)} -- the "
            f"scan found nothing, which is not the same as finding nothing wrong"
        )

    defined: set[str] = set()
    bound: set[str] = set()
    calls: list[tuple[Path, ast.Call, str]] = []
    trees: list[tuple[Path, ast.Module, list[str]]] = []

    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        trees.append((path, tree, text.splitlines()))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                defined.add(node.name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Attribute):
                        bound.add(target.attr)
                    elif isinstance(target, ast.Name):
                        bound.add(target.id)
            elif isinstance(node, ast.AnnAssign) and isinstance(
                node.target, ast.Attribute
            ):
                bound.add(node.target.attr)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                bound.add(node.value)

    for path, tree, lines in trees:
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(
                node.func, ast.Attribute
            ):
                continue
            name = node.func.attr
            if not name.startswith("_") or name.startswith("__"):
                continue
            calls.append((path, node, lines[node.lineno - 1].strip()))

    found = [
        UnresolvedCall(_sources.display(path, ROOT), node.lineno, node.func.attr, source)
        for path, node, source in calls
        if node.func.attr not in defined
        and node.func.attr not in bound
        and node.func.attr not in EXTERNAL
    ]
    found.sort(key=lambda c: (c.name, c.file, c.line))
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", action="store_true", help="print the count only")
    parser.add_argument("--json", action="store_true", help="machine-readable")
    parser.add_argument("--top", type=int, default=30, help="0 for all")
    args = parser.parse_args(argv)

    try:
        found = measure()
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.count:
        print(len(found))
        return 0
    if args.json:
        print(json.dumps([asdict(c) for c in found], indent=2))
        return 0

    print("Calls to methods this checkout defines nowhere (ADR-0058)")
    print("=" * 72)
    shown = found if args.top == 0 else found[: args.top]
    for item in shown:
        print(item)
    if len(found) > len(shown):
        print(f"  ... and {len(found) - len(shown)} more (--top 0 for all)")
    print("-" * 72)
    names = sorted({c.name for c in found})
    print(f"\n{len(found)} call site(s) over {len(names)} name(s)")
    print(f"  {len(EXTERNAL)} name(s) allowed as external, see EXTERNAL")
    print("\nRatchet it:")
    print("  python tooling/architecture/py_unresolved_calls.py --count \\")
    print("      | xargs python tooling/ratchet/ratchet.py unresolved_calls --count")
    return 0


if __name__ == "__main__":
    sys.exit(main())

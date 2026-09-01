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
from _repo_root import find_odoo_root, sibling_repos_root

ROOT = find_odoo_root(Path(__file__).resolve(), tool="py_docstring_at_runtime")

SCOPE = ROOT / "odoo"

DEFAULT_ADDON = "core"

ALL_ADDONS = "addons"

SIBLING_SCOPES = ("enterprise", "agromarin")

GOVERNED_ADDONS = (DEFAULT_ADDON, ALL_ADDONS, *SIBLING_SCOPES)

DUNDER = "__doc__"


def addon_src(addon: str = DEFAULT_ADDON) -> Path:
    if addon == DEFAULT_ADDON:
        return SCOPE
    if addon == ALL_ADDONS:
        return ROOT / "addons"
    if addon in SIBLING_SCOPES:
        return sibling_repos_root(ROOT) / addon
    return ROOT / "addons" / addon


@dataclass(frozen=True)
class Offence:
    file: str
    line: int
    kind: str
    what: str

    def __str__(self) -> str:
        return f"  {self.kind:10}  {self.file}:{self.line}  {self.what}"


def iter_source_files(src: Path | None = None) -> list[Path]:
    return sorted(
        p
        for p in (SCOPE if src is None else src).rglob("*.py")
        if "__pycache__" not in p.parts and not _sources.is_test_path(p)
    )


def _reads_doc(node: ast.AST) -> bool:
    if isinstance(node, ast.Attribute):
        return node.attr == DUNDER
    return isinstance(node, ast.Name) and node.id == DUNDER


def _hazard(node: ast.AST, parent: ast.AST | None) -> str | None:
    if isinstance(parent, ast.Attribute) and parent.value is node:
        return "attribute"
    if isinstance(parent, ast.Subscript) and parent.value is node:
        return "subscript"
    if (
        isinstance(parent, ast.Call)
        and isinstance(parent.func, ast.Attribute)
        and parent.func.value is node
    ):
        return "method"
    if isinstance(parent, (ast.BinOp, ast.AugAssign)):
        return "operand"
    return None


def measure(
    files: list[Path] | None = None,
    src: Path | None = None,
) -> list[Offence]:
    if files is None:
        files = iter_source_files(src)
        if not files:
            raise RuntimeError(
                f"no Python sources under {SCOPE if src is None else src} -- the "
                f"scan found nothing, which is not the same as finding nothing wrong"
            )
    found: list[Offence] = []
    for path in files:
        try:
            tree = ast.parse(path.read_bytes())
        except SyntaxError:
            continue
        parents: dict[int, ast.AST] = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[id(child)] = node
        display = _sources.display(path, ROOT)
        for node in ast.walk(tree):
            if not _reads_doc(node):
                continue
            kind = _hazard(node, parents.get(id(node)))
            if kind is None:
                continue
            found.append(Offence(display, node.lineno, kind, ast.unparse(node)[:60]))
    found.sort(key=lambda f: (f.file, f.line))
    return found


SCOPES = (DEFAULT_ADDON, ALL_ADDONS, *SIBLING_SCOPES)


def _render(by_scope: dict[str, list[Offence]]) -> str:
    lines = [
        "Runtime code that breaks when a docstring is None (ADR-0076)",
        "=" * 72,
    ]
    total = 0
    for scope, found in by_scope.items():
        total += len(found)
        lines.append(f"  {scope:11} {len(found)} site(s)")
        lines.extend(str(f) for f in found)
    lines.append("-" * 72)
    if total:
        lines += [
            f"{total} site(s) would raise once the docstring is gone.",
            "Read the text from an attribute the strip cannot remove, or",
            'write `(x.__doc__ or "")`.  See ADR-0076.',
        ]
    else:
        lines.append("No runtime code depends on a docstring. \u2713")
    return "\n".join(lines)


def check() -> dict[str, list[Offence]]:
    out: dict[str, list[Offence]] = {}
    for scope in SCOPES:
        src = addon_src(scope)
        if not src.is_dir():
            continue
        out[scope] = measure(src=src)
    if DEFAULT_ADDON not in out:
        raise RuntimeError(
            f"no {SCOPE} to scan -- a gate that finds no inputs reports no "
            f"findings, which is not the same as finding nothing wrong"
        )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Gate runtime reads of __doc__ that a strip turns into None."
    )
    parser.add_argument("--check", action="store_true", help="CI mode: exit 1 on drift")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    try:
        by_scope = check()
    except RuntimeError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(
            json.dumps(
                {
                    scope: [asdict(f) for f in found]
                    for scope, found in by_scope.items()
                },
                indent=2,
            )
        )
    else:
        print(_render(by_scope))
    drifted = any(by_scope.values())
    return 1 if (drifted and args.check) else 0


if __name__ == "__main__":
    sys.exit(main())

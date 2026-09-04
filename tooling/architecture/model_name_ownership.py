"""One model name, one owning module.

decision=A model declared with a bare `_name` in two modules is a silent
replace, not an error, so the registry keeps whichever module the graph
loaded last and the other module's fields and methods vanish from it.

`registration.py` warns when it happens and the loader exits 0, which is the
whole problem: install succeeds, the earlier module's code goes on calling
methods that now belong to a different app, and PostgreSQL keeps the loser's
column as an orphan while retyping any column the two shared.  A crash would
be cheaper, because a crash is attributable.

The question is relational and therefore workspace-wide.  Two modules in one
checkout are the easy case; the instance that motivated this gate was the
community `approval` against the enterprise `approvals*` family, which no
single-scope scan can see because each scope reads clean on its own.  So this
gate takes no `--addon`: it walks every checkout present and compares the
whole population at once, the same reason `js_private_access.py` needs its
`--cross-tree` scope.

A module that means to add to an existing model says `_inherit`.  That is the
one-line difference this gate is asking for, and it is why the check is a
hard zero rather than a ratchet: there is no such thing as a tolerable amount
of two modules owning one model name.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root, find_workspace, sibling_repo_paths

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _ast_cache

ROOT = find_odoo_root(Path(__file__).resolve(), tool="model_name_ownership")

CHECKOUT_ROOTS = ("odoo/addons", "addons")

# `tests/` is skipped on purpose rather than by habit.  A production model
# lives under `models/`; a class under `tests/` is scaffolding, and
# `test_backend_differential.py` legitimately declares `ir.attachment` and
# `ir.model.data` stubs for an isolated in-memory registry that no production
# database ever sees.  Reporting those would make the gate's hard zero
# unreachable and teach the next reader to ignore it.
SKIP_DIRS = frozenset(
    {"__pycache__", "node_modules", ".git", "static", "migrations", "tests"}
)


@dataclass(frozen=True)
class Declaration:
    model: str
    module: str
    path: str
    line: int


def _module_of(path: Path) -> str | None:
    for parent in path.parents:
        if (parent / "__manifest__.py").is_file():
            return parent.name
    return None


def _iter_python_files(root: Path):
    for path in sorted(root.rglob("*.py")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        yield path


def _string_value(node: ast.expr | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _string_list(node: ast.expr | None) -> list[str]:
    if (value := _string_value(node)) is not None:
        return [value]
    if isinstance(node, ast.List | ast.Tuple):
        return [v for v in (_string_value(e) for e in node.elts) if v is not None]
    return []


def _declarations_in(tree: ast.Module, module: str, path: Path) -> list[Declaration]:
    """Ask exactly the question `registration.py` asks.

    A class is an *extension* when its `_name` appears among its `_inherit`
    entries, and an original declaration otherwise.  Naming mixins in
    `_inherit` does not make it an extension -- `res.partner` declares
    `_name` beside seven mixins and is still the one module that owns the
    name -- so a gate that merely looks for the presence of `_inherit`
    reports nothing about the models most worth protecting.
    """
    found: list[Declaration] = []
    for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
        name: str | None = None
        parents: list[str] = []
        for stmt in cls.body:
            if not isinstance(stmt, ast.Assign):
                continue
            for target in stmt.targets:
                if not isinstance(target, ast.Name):
                    continue
                if target.id == "_name":
                    name = _string_value(stmt.value) or name
                elif target.id == "_inherit":
                    parents = _string_list(stmt.value)
        if name and name not in parents:
            found.append(Declaration(name, module, str(path), cls.lineno))
    return found


def scan_roots() -> list[Path]:
    roots = [ROOT / part for part in CHECKOUT_ROOTS]
    roots += [
        sibling / part
        for sibling in sibling_repo_paths(ROOT)
        for part in CHECKOUT_ROOTS
    ]
    roots += sibling_repo_paths(ROOT)
    seen: dict[Path, None] = {}
    for root in roots:
        if root.is_dir():
            seen.setdefault(root.resolve(), None)
    return [root for root in seen if not _covered_by(root, seen)]


def _covered_by(root: Path, others) -> bool:
    return any(other != root and other in root.parents for other in others)


def collect(roots=None) -> dict[str, list[Declaration]]:
    by_model: dict[str, list[Declaration]] = {}
    for root in roots if roots is not None else scan_roots():
        for path in _iter_python_files(root):
            module = _module_of(path)
            if module is None:
                continue
            tree = _ast_cache.parse_file(path)
            for decl in _declarations_in(tree, module, path):
                by_model.setdefault(decl.model, []).append(decl)
    return by_model


def measure(roots=None) -> list[tuple[str, list[Declaration]]]:
    declared = collect(roots)
    if not declared:
        raise RuntimeError(
            "no model declarations found in any checkout. A contested name is "
            "a comparison between two modules, so a scan that reaches none "
            "reports zero for the same reason a clean tree does."
        )
    contested = []
    for model, decls in declared.items():
        modules = {decl.module for decl in decls}
        if len(modules) > 1:
            contested.append((model, sorted(decls, key=lambda d: (d.module, d.path))))
    contested.sort()
    return contested


def _report(contested) -> None:
    print(f"Models owned by two or more modules: {len(contested)}")
    for model, decls in contested:
        print(f"\n  {model}")
        for decl in decls:
            print(f"    {decl.module:24} {decl.path}:{decl.line}")
    if contested:
        print(
            "\nEach of these is a silent replace: the module the graph loads "
            "last wins the\nregistry and the others lose their fields and "
            "methods, with the install still\nexiting 0. A module that means "
            "to add to an existing model says _inherit."
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check", action="store_true", help="exit 1 when any model is contested"
    )
    parser.add_argument("--count", action="store_true", help="print the count only")
    parser.add_argument("--json", action="store_true", help="machine-readable")
    args = parser.parse_args(argv)

    try:
        contested = measure()
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.count:
        print(len(contested))
    elif args.json:
        print(
            json.dumps(
                [
                    {"model": model, "declarations": [asdict(d) for d in decls]}
                    for model, decls in contested
                ],
                indent=2,
            )
        )
    else:
        _report(contested)
        workspace = find_workspace(ROOT)
        print(
            f"\nScanned: {', '.join(str(r) for r in scan_roots())}"
            if workspace is None
            else f"\nWorkspace: {workspace}  ({len(scan_roots())} roots)"
        )

    if args.check and contested:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

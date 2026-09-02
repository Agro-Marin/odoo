#!/usr/bin/env python3
"""A count asked only whether it is nonzero takes a limit.

A `search_count` whose result is consumed by an `if`, a `not`, a `bool()` or a
comparison against 0 scans the whole table to decide whether the first row
exists. `limit=1` makes the result 0 or 1 and none of those consumers can tell
the difference, so the rewrite is one keyword and O(rows) becomes O(1). A
count used inside a larger expression is excluded, because the value escapes
there; where the number itself is wanted, an unlimited `search_count` is
correct and stays.
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _count_gate
import _sources
from _repo_root import find_odoo_root, sibling_repos_root

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _ast_cache

ROOT = find_odoo_root(Path(__file__).resolve(), tool="py_count_as_boolean")

SCOPE = ROOT / "odoo"

DEFAULT_ADDON = "core"

ALL_ADDONS = "addons"

TESTS = "tests"

SIBLING_SCOPES = ("enterprise", "agromarin")

GOVERNED_ADDONS = (DEFAULT_ADDON, ALL_ADDONS, TESTS, *SIBLING_SCOPES)

METHOD = "search_count"


def addon_src(addon: str = DEFAULT_ADDON) -> Path:
    if addon == DEFAULT_ADDON:
        return SCOPE
    if addon == ALL_ADDONS:
        return ROOT / "addons"
    if addon == TESTS:
        return SCOPE / "tests"
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
        return f"  {self.kind:12}  {self.file}:{self.line}  {self.what}"


def iter_source_files(src: Path | None = None) -> list[Path]:
    root = SCOPE if src is None else src
    # odoo/tests is the test FRAMEWORK -- TransactionCase, Form, the CDP driver,
    # the suite runner -- production code that every addon test runs on. It is
    # excluded from the default scan only because is_test_path matches any path
    # with a `tests` component, so scanning it needs that filter lifted. Real
    # test suites (odoo/orm/tests and the rest) stay out, which is the point of
    # the filter; this is the one tree the name gets wrong.
    tests_root = root == SCOPE / "tests"
    return sorted(
        p
        for p in root.rglob("*.py")
        if "__pycache__" not in p.parts and (tests_root or not _sources.is_test_path(p))
    )


def _truth_use(call: ast.Call, parent: ast.AST | None) -> str | None:
    if isinstance(parent, (ast.If, ast.IfExp)) and parent.test is call:
        return "if"
    if isinstance(parent, ast.UnaryOp) and isinstance(parent.op, ast.Not):
        return "not"
    if (
        isinstance(parent, ast.Call)
        and isinstance(parent.func, ast.Name)
        and parent.func.id == "bool"
    ):
        return "bool()"
    if isinstance(parent, ast.Compare) and len(parent.ops) == 1:
        other = parent.comparators[0] if parent.left is call else parent.left
        if isinstance(other, ast.Constant) and other.value == 0:
            return "vs 0"
    if (
        isinstance(parent, (ast.While, ast.Assert))
        and getattr(parent, "test", None) is call
    ):
        return "if"
    return None


def _consumer(call: ast.Call, parents: dict[int, ast.AST]) -> str | None:
    node: ast.AST = call
    while True:
        parent = parents.get(id(node))
        use = _truth_use(node, parent)
        if use:
            return use
        if isinstance(parent, ast.BoolOp) or (
            isinstance(parent, ast.UnaryOp) and isinstance(parent.op, ast.Not)
        ):
            node = parent
            continue
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
        tree = _ast_cache.parse_file(path)
        parents: dict[int, ast.AST] = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[id(child)] = node
        display = _sources.display(path, ROOT)
        for call in ast.walk(tree):
            if not (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == METHOD
            ):
                continue
            if len(call.args) > 1 or any(k.arg == "limit" for k in call.keywords):
                continue
            use = _consumer(call, parents)
            if use:
                found.append(Offence(display, call.lineno, use, ast.unparse(call)[:70]))
    found.sort(key=lambda f: (f.file, f.line))
    return found


def main(argv: list[str] | None = None) -> int:
    return _count_gate.run(
        argv,
        script="py_count_as_boolean.py",
        gate="py_count_as_boolean",
        headline="Counts asked only whether they are nonzero, with no limit ({where})",
        unit="site(s)",
        default_addon=DEFAULT_ADDON,
        everything=ALL_ADDONS,
        siblings=SIBLING_SCOPES,
        governed=GOVERNED_ADDONS,
        addon_src=addon_src,
        measure=measure,
        root_name=ROOT.name,
        summary=lambda found: "  each is one keyword: search_count(domain, limit=1)",
    )


if __name__ == "__main__":
    sys.exit(main())

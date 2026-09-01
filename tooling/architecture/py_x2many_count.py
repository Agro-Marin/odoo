#!/usr/bin/env python3

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _count_gate
import _sources
from _repo_root import find_odoo_root, sibling_repos_root

ROOT = find_odoo_root(Path(__file__).resolve(), tool="py_x2many_count")

SCOPE = ROOT / "odoo"

DEFAULT_ADDON = "core"

ALL_ADDONS = "addons"

TESTS = "tests"

SIBLING_SCOPES = ("enterprise", "agromarin")

GOVERNED_ADDONS = (
    DEFAULT_ADDON,
    ALL_ADDONS,
    TESTS,
    "mail",
    "account",
    "stock",
    "project",
    *SIBLING_SCOPES,
)

RELATIONAL_SUFFIX = "_ids"


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
class HandCount:
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


def _counter_assignment(node: ast.AST) -> str | None:
    if not (isinstance(node, ast.Assign) and len(node.targets) == 1):
        return None
    target, value = node.targets[0], node.value
    if not (isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name)):
        return None
    if not (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Name)
        and value.func.id == "len"
        and len(value.args) == 1
    ):
        return None
    arg = value.args[0]
    if not (isinstance(arg, ast.Attribute) and isinstance(arg.value, ast.Name)):
        return None
    if arg.value.id != target.value.id:
        return None
    return arg.attr if arg.attr.endswith(RELATIONAL_SUFFIX) else None


def _guards_unsaved(test: ast.AST) -> bool:
    src = ast.unparse(test)
    return "self._ids" in src or "NewId" in src


def _loops_over_self(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.For)
        and isinstance(node.iter, ast.Name)
        and node.iter.id == "self"
    )


def measure(
    files: list[Path] | None = None,
    src: Path | None = None,
) -> list[HandCount]:
    if files is None:
        files = iter_source_files(src)
        if not files:
            raise RuntimeError(
                f"no Python sources under {SCOPE if src is None else src} -- the "
                f"scan found nothing, which is not the same as finding nothing wrong"
            )
    found: list[HandCount] = []
    for path in files:
        try:
            tree = ast.parse(path.read_bytes())
        except SyntaxError:
            continue
        display = _sources.display(path, ROOT)
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not fn.name.startswith("_compute"):
                continue
            stack: list[tuple[ast.AST, bool]] = [(fn, False)]
            while stack:
                node, unsaved = stack.pop()
                for child in ast.iter_child_nodes(node):
                    child_unsaved = unsaved or (
                        isinstance(node, ast.If)
                        and child in node.body
                        and _guards_unsaved(node.test)
                    )
                    if (
                        field := _counter_assignment(child)
                    ) is not None and not child_unsaved:
                        found.append(
                            HandCount(
                                display, child.lineno, "len", f"{fn.name} -> {field}"
                            )
                        )
                    stack.append((child, child_unsaved))
            for node in ast.walk(fn):
                if not _loops_over_self(node):
                    continue
                found.extend(
                    HandCount(display, inner.lineno, "search_count", fn.name)
                    for inner in ast.walk(node)
                    if isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Attribute)
                    and inner.func.attr == "search_count"
                )
    found.sort(key=lambda f: (f.file, f.line))
    return found


def main(argv: list[str] | None = None) -> int:
    return _count_gate.run(
        argv,
        script="py_x2many_count.py",
        gate="py_x2many_count",
        headline="Counters that count by hand (ADR-0052, {where})",
        unit="counter(s)",
        default_addon=DEFAULT_ADDON,
        everything=ALL_ADDONS,
        siblings=SIBLING_SCOPES,
        governed=GOVERNED_ADDONS,
        addon_src=addon_src,
        measure=measure,
        root_name=ROOT.name,
        summary=lambda found: "  len(x2many): {}   search_count in a loop: {}".format(
            sum(1 for f in found if f.kind == "len"),
            sum(1 for f in found if f.kind == "search_count"),
        ),
        where_for=lambda addon: {DEFAULT_ADDON: "odoo/", ALL_ADDONS: "addons/"}.get(
            addon,
            f"{addon}/" if addon in SIBLING_SCOPES else f"addons/{addon}/",
        ),
        addon_help_tail=", and anything else is that one module under addons/",
    )


if __name__ == "__main__":
    sys.exit(main())

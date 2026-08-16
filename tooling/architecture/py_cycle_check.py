#!/usr/bin/env python3


from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

ADR = "0034"

REPO_ROOT = find_odoo_root(Path(__file__).resolve(), tool="py_cycle_check")
CORE = REPO_ROOT / "odoo"

EXCLUDED_SUBPACKAGES = frozenset({"addons", "upgrade_code"})


@dataclass(frozen=True)
class Known:
    members: tuple[str, ...]
    reason: str

    @property
    def key(self) -> tuple[str, ...]:
        return tuple(sorted(self.members))


_PACKAGE_REEXPORT = (
    "The benign package<->submodule shape: the package's __init__ imports the "
    "submodule and the submodule imports a name back from the package. Python "
    "resolves it through the partially-initialised module, and it holds because "
    "the submodule's import runs while __init__ is already on the stack. It is "
    "still an ordering dependency: importing the submodule FIRST is what makes "
    "it fragile, so it is pinned rather than blessed."
)

KNOWN_CYCLES: tuple[Known, ...] = (
    Known(
        (
            "odoo.service",
            "odoo.service._prefork",
            "odoo.service._threaded",
            "odoo.service.server",
        ),
        _PACKAGE_REEXPORT,
    ),
    Known(("odoo.modules", "odoo.modules.db"), _PACKAGE_REEXPORT),
    Known(("odoo.cli", "odoo.cli.command"), _PACKAGE_REEXPORT),
    Known(
        ("odoo.tests", "odoo.tests.common", "odoo.tests.http"),
        "The package<->submodule shape with one submodule<->submodule edge, and "
        "the only cycle here that is documented AT THE SOURCE: common.py ends "
        "with `from .http import (...)` under the comment 'Imported last on "
        "purpose: odoo.tests.http imports from this module, so hoisting this to "
        "the top makes the cycle unresolvable.' So it is managed, not "
        "accidental -- but it was invisible rather than tolerated: odoo/tests/ "
        "was dropped wholesale by the old directory-name filter, so the gate "
        "reported 323 modules and zero unpinned cycles over a graph that never "
        "contained the test framework. Pinned to make the existing decision "
        "visible. Removing it means re-exporting HttpCase from somewhere that "
        "is not common.py.",
    ),
)


@dataclass
class Report:
    modules: int = 0
    edges: int = 0
    cycles: list[tuple[str, ...]] = field(default_factory=list)
    new: list[tuple[str, ...]] = field(default_factory=list)
    known: list[tuple[str, ...]] = field(default_factory=list)
    stale_pins: list[tuple[str, ...]] = field(default_factory=list)
    edge_lines: dict[tuple[str, str], int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.new and not self.stale_pins


def _is_type_checking(test: ast.expr) -> bool:
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    if isinstance(test, ast.Attribute):
        return test.attr == "TYPE_CHECKING"
    return False


class _ModuleLevelImports(ast.NodeVisitor):
    def __init__(self, module: str, is_init: bool) -> None:
        self.module, self.is_init = module, is_init
        self.found: list[tuple[str, int]] = []
        self._depth = 0

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._depth += 1
        self.generic_visit(node)
        self._depth -= 1

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

    def _resolve(self, module: str | None, level: int) -> str:
        base = self.module if self.is_init else self.module.rsplit(".", 1)[0]
        for _ in range(level - 1):
            base = base.rsplit(".", 1)[0] if "." in base else ""
        if module:
            return f"{base}.{module}" if base else module
        return base

    def visit_Import(self, node: ast.Import) -> None:
        if not self._depth:
            for alias in node.names:
                self.found.append((alias.name, node.lineno))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if self._depth:
            return
        base = (
            self._resolve(node.module, node.level)
            if node.level
            else (node.module or "")
        )
        if not base:
            return
        self.found.append((base, node.lineno))
        for alias in node.names:
            if alias.name != "*":
                self.found.append((f"{base}.{alias.name}", node.lineno))

    def visit_If(self, node: ast.If) -> None:
        if _is_type_checking(node.test):
            for child in node.orelse:
                self.visit(child)
            return
        self.generic_visit(node)


def module_name_for(path: Path) -> str:
    parts = list(path.relative_to(REPO_ROOT).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


_CORE_TEST_FRAMEWORK_PACKAGE = ("tests",)


def _is_test_file(rel: tuple[str, ...], name: str) -> bool:
    if rel[: len(_CORE_TEST_FRAMEWORK_PACKAGE)] == _CORE_TEST_FRAMEWORK_PACKAGE:
        return name.startswith("test_") or name == "conftest.py"
    return "tests" in rel or name.startswith("test_") or name == "conftest.py"


def iter_source_files() -> list[Path]:
    out = []
    for path in sorted(CORE.rglob("*.py")):
        rel = path.relative_to(CORE).parts
        if rel[0] in EXCLUDED_SUBPACKAGES or "__pycache__" in rel:
            continue
        if _is_test_file(rel, path.name):
            continue
        out.append(path)
    return out


def build_graph(files: list[Path] | None = None):
    files = iter_source_files() if files is None else files
    modules = {module_name_for(p): p for p in files}
    edges: dict[str, set[str]] = {m: set() for m in modules}
    edge_lines: dict[tuple[str, str], int] = {}
    for path in files:
        name = module_name_for(path)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError) as exc:  # pragma: no cover
            print(f"warning: could not parse {path}: {exc}", file=sys.stderr)
            continue
        collector = _ModuleLevelImports(name, path.name == "__init__.py")
        collector.visit(tree)
        for target, lineno in collector.found:
            candidate = target
            while candidate and candidate not in modules:
                if "." not in candidate:
                    candidate = ""
                    break
                candidate = candidate.rsplit(".", 1)[0]
            if candidate and candidate != name:
                if candidate not in edges[name]:
                    edge_lines[(name, candidate)] = lineno
                edges[name].add(candidate)
    return modules, edges, edge_lines


def strongly_connected(nodes, edges) -> list[list[str]]:
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: dict[str, bool] = {}
    stack: list[str] = []
    result: list[list[str]] = []
    counter = 0

    for root in sorted(nodes):
        if root in index:
            continue
        work = [(root, iter(sorted(edges.get(root, ()))))]
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack[root] = True
        while work:
            node, it = work[-1]
            descended = False
            for nxt in it:
                if nxt not in index:
                    index[nxt] = low[nxt] = counter
                    counter += 1
                    stack.append(nxt)
                    on_stack[nxt] = True
                    work.append((nxt, iter(sorted(edges.get(nxt, ())))))
                    descended = True
                    break
                if on_stack.get(nxt):
                    low[node] = min(low[node], index[nxt])
            if descended:
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[node])
            if low[node] == index[node]:
                component = []
                while True:
                    member = stack.pop()
                    on_stack[member] = False
                    component.append(member)
                    if member == node:
                        break
                result.append(component)
    return result


def check(files: list[Path] | None = None) -> Report:
    modules, edges, edge_lines = build_graph(files)
    report = Report(
        modules=len(modules),
        edges=sum(len(v) for v in edges.values()),
        edge_lines=edge_lines,
    )
    pinned = {k.key for k in KNOWN_CYCLES}
    seen = set()
    for component in strongly_connected(set(modules), edges):
        if len(component) < 2:
            only = component[0]
            if only not in edges.get(only, ()):
                continue
        key = tuple(sorted(component))
        seen.add(key)
        report.cycles.append(key)
        (report.known if key in pinned else report.new).append(key)
    report.stale_pins = sorted(pinned - seen)
    return report


def _render(report: Report) -> str:
    lines = [
        "Python import-cycle check",
        "=" * 64,
        f"core modules: {report.modules}   module-level import edges: {report.edges}",
        f"cycles: {len(report.cycles)}",
        "-" * 64,
    ]
    for key in report.new:
        lines.append(f"\nNEW cycle ({len(key)} modules):")
        lines.extend(f"    {member}" for member in key)
    lines.extend(
        f"\nSTALE pin (cycle is gone — remove it from KNOWN_CYCLES): {key}"
        for key in report.stale_pins
    )
    if report.known:
        lines.append(f"\n{len(report.known)} known cycle(s) tolerated (tracked debt):")
        lines.extend(f"    {' <-> '.join(key)}" for key in report.known)
    lines.append("")
    lines.append(
        "No new import cycles. ✓"
        if report.ok
        else "FAILED: the import graph gained a cycle."
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gate Python import cycles in odoo/.")
    parser.add_argument("--check", action="store_true", help="CI mode: exit 1 on drift")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    report = check()
    if args.json:
        print(
            json.dumps(
                {
                    "ok": report.ok,
                    "modules": report.modules,
                    "edges": report.edges,
                    "new": [list(c) for c in report.new],
                    "known": [list(c) for c in report.known],
                    "stale_pins": [list(c) for c in report.stale_pins],
                },
                indent=2,
            )
        )
    else:
        print(_render(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())

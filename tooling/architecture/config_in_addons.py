#!/usr/bin/env python3
"""Addon code reaching for `odoo.tools.config`, as a ratchet.

`odoo.tools.config` is one process-global, mutable, string-keyed mapping of
every option the server knows -- about 114 of them -- and until 2026-09 it had
no boundary at all: 58 core files read it, four core sites and over a hundred
test sites wrote it, and `tests/service/test_db.py` had to substitute a
`_MockConfig(dict)` for the whole object to test anything that touched a key.
The core now reads typed, frozen snapshots instead -- `odoo.db.settings.
PoolSettings`, `odoo.http.settings.HttpSettings`, `odoo.service.settings.
ServerSettings` -- each built once at boot from the option dict, so a
subsystem names the fields it depends on and a test installs a snapshot rather
than mutating a global.

Addon code is the other half of the population and is not migrated: it reads
`config["dev_mode"]` to decide how much to log, `config.filestore(db)` to find
an attachment, `config["test_enable"]` to skip a network call. Each of those is
a direct dependency on the process-global, invisible to every import gate --
`odoo.tools` is the sanctioned door for addons -- and so growing with every
module. This gate counts them.

The unit is REFERENCES, not files: every expression in a non-test addon file
that evaluates to the config object -- `config[...]`, `config.get(...)`,
`config.filestore(...)`, `config.options[...]`, a bare `config` handed to a
helper -- whether the name arrived as `from odoo.tools import config`, `from
odoo.tools.config import config`, `from odoo import tools` then
`tools.config`, or `import odoo` then `odoo.tools.config`. One file that
reaches the dict nine times is nine couplings to remove, not one, and the
migration that lands is per read. A module-level `config` that is not odoo's
(a local variable, a parameter, a model field) is not counted: only names the
module binds by importing from `odoo.tools` are followed, and a function that
rebinds the name as a parameter shadows it for its body. Test files are out of
scope: a test that sets an option is exercising the option on purpose. The
addons tree is `addons/` and `odoo/addons/` as one number; a sibling checkout
measures its own tree.
"""

from __future__ import annotations

import ast
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _count_gate
import _sources
from _repo_root import find_odoo_root

ROOT = find_odoo_root(Path(__file__).resolve(), tool="config_in_addons")

BUNDLED_TREES = ("addons", "odoo/addons")

DEFAULT_ADDON = "addons"

GOVERNED_ADDONS = (DEFAULT_ADDON,)

CONFIG_MODULES = frozenset({"odoo.tools", "odoo.tools.config"})


def addon_src(addon: str = DEFAULT_ADDON) -> Path:
    return ROOT


@dataclass(frozen=True)
class ConfigReference:
    file: str
    line: int
    shape: str

    def __str__(self) -> str:
        return f"  {self.file}:{self.line}  {self.shape}"


def iter_source_files(src: Path | None = None) -> list[Path]:
    root = ROOT if src is None else src
    files: list[Path] = []
    for tree in BUNDLED_TREES:
        files.extend(_sources.iter_python_files(root / tree, include_polyglots=False))
    return sorted(files)


class _Bindings:
    __slots__ = ("config_names", "odoo_names", "tools_names")

    def __init__(self, tree: ast.Module) -> None:
        self.config_names: set[str] = set()
        self.tools_names: set[str] = set()
        self.odoo_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and not node.level:
                module = node.module or ""
                for alias in node.names:
                    bound = alias.asname or alias.name
                    if module in CONFIG_MODULES and alias.name == "config":
                        self.config_names.add(bound)
                    elif module == "odoo" and alias.name == "tools":
                        self.tools_names.add(bound)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "odoo.tools" and alias.asname:
                        self.tools_names.add(alias.asname)
                    elif alias.name.split(".", 1)[0] == "odoo":
                        self.odoo_names.add(alias.asname or "odoo")

    def is_config(self, node: ast.expr, shadowed: set[str]) -> bool:
        if isinstance(node, ast.Name):
            return node.id in self.config_names and node.id not in shadowed
        if not (isinstance(node, ast.Attribute) and node.attr == "config"):
            return False
        base = node.value
        if isinstance(base, ast.Name):
            return base.id in self.tools_names and base.id not in shadowed
        return (
            isinstance(base, ast.Attribute)
            and base.attr == "tools"
            and isinstance(base.value, ast.Name)
            and base.value.id in self.odoo_names
            and base.value.id not in shadowed
        )


def _shape(parent: ast.AST | None) -> str:
    if isinstance(parent, ast.Subscript):
        return "config[...]"
    if isinstance(parent, ast.Attribute):
        return f"config.{parent.attr}"
    return "config"


class _ReferenceCollector(ast.NodeVisitor):
    def __init__(self, bindings: _Bindings) -> None:
        self.bindings = bindings
        self.found: list[tuple[int, str]] = []
        self._scopes: list[set[str]] = [set()]
        self._parents: list[ast.AST] = []

    def _shadowed(self) -> set[str]:
        return set().union(*self._scopes)

    def _visit_scope(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda
    ) -> None:
        args = node.args
        names = {
            a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs) if a.arg
        }
        if args.vararg:
            names.add(args.vararg.arg)
        if args.kwarg:
            names.add(args.kwarg.arg)
        self._scopes.append(names)
        try:
            self.generic_visit(node)
        finally:
            self._scopes.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_scope(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_scope(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._visit_scope(node)

    def generic_visit(self, node: ast.AST) -> None:
        self._parents.append(node)
        try:
            super().generic_visit(node)
        finally:
            self._parents.pop()

    def _record(self, node: ast.expr) -> None:
        parent = self._parents[-1] if self._parents else None
        self.found.append((node.lineno, _shape(parent)))

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load) and self.bindings.is_config(
            node, self._shadowed()
        ):
            self._record(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if self.bindings.is_config(node, self._shadowed()):
            self._record(node)
            return
        self.generic_visit(node)


def references_in(tree: ast.Module) -> list[tuple[int, str]]:
    bindings = _Bindings(tree)
    if not (bindings.config_names or bindings.tools_names or bindings.odoo_names):
        return []
    collector = _ReferenceCollector(bindings)
    collector.visit(tree)
    return sorted(collector.found)


def measure(
    files: list[Path] | None = None,
    src: Path | None = None,
) -> list[ConfigReference]:
    if files is None:
        files = iter_source_files(src)
        if not files:
            root = ROOT if src is None else src
            raise RuntimeError(
                f"no Python sources under {' or '.join(str(root / t) for t in BUNDLED_TREES)}"
                f" -- the scan found nothing, which is not the same as finding "
                f"nothing wrong"
            )
    found: list[ConfigReference] = []
    for path in files:
        try:
            tree = ast.parse(path.read_bytes())
        except SyntaxError:
            continue
        shown = _sources.display(path, ROOT)
        found.extend(
            ConfigReference(shown, line, shape) for line, shape in references_in(tree)
        )
    found.sort(key=lambda item: (item.file, item.line))
    return found


def _summary(found: list[ConfigReference]) -> str:
    by_shape = Counter(item.shape for item in found)
    by_file = Counter(item.file for item in found)
    shapes = ", ".join(f"{shape} {count}" for shape, count in by_shape.most_common(6))
    return f"  in {len(by_file)} file(s); by shape: {shapes}"


def main(argv: list[str] | None = None) -> int:
    return _count_gate.run(
        argv,
        script="config_in_addons.py",
        gate="config_in_addons",
        headline="Addon references to the process-global odoo.tools.config ({where})",
        unit="reference(s)",
        default_addon=DEFAULT_ADDON,
        everything=DEFAULT_ADDON,
        siblings=(),
        governed=GOVERNED_ADDONS,
        addon_src=addon_src,
        measure=measure,
        root_name=ROOT.name,
        summary=_summary,
        where_for=lambda addon: "addons/ and odoo/addons/",
        addon_help=(
            f"what to measure: {DEFAULT_ADDON} (default, and the only scope) is "
            f"the two bundled trees, addons/ and odoo/addons/, as one number"
        ),
        description=__doc__,
    )


if __name__ == "__main__":
    sys.exit(main())

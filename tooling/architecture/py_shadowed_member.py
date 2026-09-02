#!/usr/bin/env python3
"""A class body defines each member once.

A second `def`, nested `class` or assignment of a name already bound in the
same class body is a defect: Python keeps the last, so the earlier definition
never runs and nothing in the file says so -- the shape a parallel edit
produces at opposite ends of a long class. `ruff`'s F811 does not see it,
because its default dummy-variable regex drops every leading-underscore name
and an Odoo model method is always one. Scope is the class body, not the
module: `test_orm` and `test_inherit` redefine module-level classes on
purpose, and `@overload`, `@property` accessors and `singledispatch.register`
redefine a name by design and are not shadows.
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

ROOT = find_odoo_root(Path(__file__).resolve(), tool="py_shadowed_member")

SCOPE = ROOT / "odoo"

DEFAULT_ADDON = "core"

ALL_ADDONS = "addons"

SIBLING_SCOPES = ("enterprise", "agromarin", "design-themes")

GOVERNED_ADDONS = (DEFAULT_ADDON, ALL_ADDONS, *SIBLING_SCOPES)

OVERLOAD_DECORATORS = frozenset({"overload", "typing.overload"})

SELF_DECLARING_SUFFIXES = (".setter", ".getter", ".deleter", ".register")


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
    klass: str
    member: str
    first: int

    def __str__(self) -> str:
        return (
            f"  {self.file}:{self.line}  {self.klass}.{self.member}  "
            f"shadows the definition at line {self.first}"
        )


def iter_source_files(src: Path) -> list[Path]:
    return sorted(p for p in src.rglob("*.py") if "__pycache__" not in p.parts)


def _kind(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    names = {ast.unparse(d).split("(")[0] for d in node.decorator_list}
    if names & OVERLOAD_DECORATORS:
        return "overload"
    if any(name.endswith(SELF_DECLARING_SUFFIXES) for name in names):
        return "declares-itself"
    return "plain"


def _members(body: list[ast.stmt]) -> list[tuple[str, int, str]]:
    named: list[tuple[str, int, str]] = []
    for statement in body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            named.append((statement.name, statement.lineno, _kind(statement)))
        elif isinstance(statement, ast.ClassDef):
            named.append((statement.name, statement.lineno, "plain"))
        elif isinstance(statement, ast.Assign):
            named.extend(
                (target.id, statement.lineno, "plain")
                for target in statement.targets
                if isinstance(target, ast.Name)
            )
    return named


def scan(path: Path, display: str) -> list[Offence]:
    tree = _ast_cache.parse_file(path)
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        seen: dict[str, int] = {}
        stubbed: set[str] = set()
        for name, line, kind in _members(node.body):
            shadows = name in seen and kind != "declares-itself"
            if shadows and name not in stubbed:
                found.append(Offence(display, line, node.name, name, seen[name]))
            if kind == "overload":
                stubbed.add(name)
            else:
                stubbed.discard(name)
            seen.setdefault(name, line)
    return found


def measure(src: Path | None = None) -> list[Offence]:
    where = SCOPE if src is None else src
    files = iter_source_files(where)
    if not files:
        raise RuntimeError(
            f"no Python sources under {where} -- the scan found nothing, which "
            f"is not the same as finding nothing wrong"
        )
    found: list[Offence] = []
    for path in files:
        found.extend(scan(path, _sources.display(path, ROOT)))
    found.sort(key=lambda f: (f.file, f.line))
    return found


def main(argv: list[str] | None = None) -> int:
    return _count_gate.run(
        argv,
        script="py_shadowed_member.py",
        gate="py_shadowed_member",
        headline=(
            "A class body defines each member once, since Python silently keeps "
            "the last ({where})"
        ),
        unit="shadowed member(s)",
        default_addon=DEFAULT_ADDON,
        everything=ALL_ADDONS,
        siblings=SIBLING_SCOPES,
        governed=GOVERNED_ADDONS,
        addon_src=addon_src,
        measure=measure,
        root_name=ROOT.name,
        summary=lambda found: "  each is one definition that never runs",
    )


if __name__ == "__main__":
    sys.exit(main())

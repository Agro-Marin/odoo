#!/usr/bin/env python3
"""`IN` over a bound value goes through the SQL builder, with a tuple.

psycopg 3 binds server-side, so an `IN %s` handed straight to `cr.execute`
reaches PostgreSQL as `IN $N` and is a syntax error for every value type. The
spelling works only through `SQL()`, whose tuple branch expands it into
`(%s, %s, ...)`; a list there is not expanded, and where a list is what the
caller has the operator is `= ANY(%s)`. The gate reports a query text with
`IN %s` executed without the builder, and an `SQL()` given a list. A hard
zero on every scope: both defects that prompted it are fixed, and zero is
what refuses the first one back.
"""

from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _count_gate
import _sources
from _repo_root import find_odoo_root, sibling_repos_root

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _ast_cache

ROOT = find_odoo_root(Path(__file__).resolve(), tool="sql_in_placeholder")

SCOPE = ROOT / "odoo"

DEFAULT_ADDON = "core"

ALL_ADDONS = "addons"

TESTS = "tests"

SIBLING_SCOPES = ("enterprise", "agromarin")

GOVERNED_ADDONS = (DEFAULT_ADDON, ALL_ADDONS, TESTS, *SIBLING_SCOPES)

SQL_KEYWORD = re.compile(
    r"\b(SELECT|INSERT|UPDATE|DELETE|WITH|FROM|WHERE|SET|VALUES|JOIN|HAVING"
    r"|GROUP BY|ORDER BY|AND|OR|ON|EXTRACT|COALESCE|DISTINCT|LIMIT|UNION|USING)\b"
)

IN_PLACEHOLDER = re.compile(
    r"\b(?:NOT\s+IN|IN)\s+%(?:\((\w+)\))?s", re.IGNORECASE | re.DOTALL
)

RAW_EXECUTORS = frozenset(
    {"execute", "executemany", "execute_query", "execute_query_dict"}
)

BUILDER = "SQL"


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
        return f"  {self.kind:14}  {self.file}:{self.line}  {self.what}"


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


def _string_of(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            v.value
            for v in node.values
            if isinstance(v, ast.Constant) and isinstance(v.value, str)
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return (_string_of(node.left) or "") + (_string_of(node.right) or "")
    return None


def _is_not_a_tuple(node: ast.AST) -> bool:
    if isinstance(node, (ast.List, ast.ListComp, ast.SetComp, ast.GeneratorExp)):
        return True
    if isinstance(node, ast.Attribute) and node.attr == "ids":
        return True
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name) and func.id in ("list", "sorted"):
            return True
        if isinstance(func, ast.Attribute) and func.attr in ("mapped", "keys"):
            return True
    return False


def _builder_argument(call: ast.Call, text: str, match: re.Match) -> ast.AST | None:
    name = match.group(1)
    if name:
        for kw in call.keywords:
            if kw.arg == name:
                return kw.value
        return None
    spots = [m.start() for m in re.finditer(r"%s", text)]
    here = text.find("%s", match.start())
    if here not in spots:
        return None
    index = spots.index(here)
    return call.args[1 + index] if 1 + index < len(call.args) else None


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
        display = _sources.display(path, ROOT)

        builder_literals: set[int] = set()
        for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
            func = call.func
            callee = (
                func.attr
                if isinstance(func, ast.Attribute)
                else getattr(func, "id", "")
            )
            if callee != BUILDER or not call.args:
                continue
            text = _string_of(call.args[0])
            if text is None or not SQL_KEYWORD.search(text):
                continue
            builder_literals.add(id(call.args[0]))
            for match in IN_PLACEHOLDER.finditer(text):
                arg = _builder_argument(call, text, match)
                if arg is not None and _is_not_a_tuple(arg):
                    found.append(
                        Offence(
                            display,
                            call.lineno,
                            "sequence",
                            f"{match.group(0).strip()} <- {ast.unparse(arg)[:60]}",
                        )
                    )

        for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
            func = call.func
            callee = (
                func.attr
                if isinstance(func, ast.Attribute)
                else getattr(func, "id", "")
            )
            if callee not in RAW_EXECUTORS or not call.args:
                continue
            arg = call.args[0]
            if id(arg) in builder_literals:
                continue
            text = _string_of(arg)
            if text is None or not SQL_KEYWORD.search(text):
                continue
            found.extend(
                Offence(display, call.lineno, "unbuilt", match.group(0).strip())
                for match in IN_PLACEHOLDER.finditer(text)
            )
    found.sort(key=lambda f: (f.file, f.line))
    return found


def main(argv: list[str] | None = None) -> int:
    return _count_gate.run(
        argv,
        script="sql_in_placeholder.py",
        gate="sql_in_placeholder",
        headline="`IN %s` reaching psycopg without the SQL builder ({where})",
        unit="site(s)",
        default_addon=DEFAULT_ADDON,
        everything=ALL_ADDONS,
        siblings=SIBLING_SCOPES,
        governed=GOVERNED_ADDONS,
        addon_src=addon_src,
        measure=measure,
        root_name=ROOT.name,
        summary=lambda found: (
            f"  no SQL() builder: "
            f"{sum(1 for f in found if f.kind == 'unbuilt')}   "
            f"builder given a non-tuple: "
            f"{sum(1 for f in found if f.kind == 'sequence')}"
        ),
    )


if __name__ == "__main__":
    sys.exit(main())

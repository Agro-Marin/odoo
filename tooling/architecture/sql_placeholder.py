"""Placeholders in raw SQL that psycopg 3 cannot bind.

Two shapes, one cause. `SQL("x IN %s", (1, 2))` rewrites the placeholder into
`x IN (%s, %s)` before the driver sees it, and psycopg 2 interpolated parameters
client-side, so both of these looked correct for as long as either was true.
psycopg 3 binds server-side and this fork uses `SQL()` or nothing:

*`IN %s` in a query string.* The statement leaves as `x IN $1`, which is not
valid SQL. Postgres answers `syntax error at or near "$1"` every single time it
runs -- there is no input that makes it work.

*A tuple passed as a parameter.* `= ANY(%s)` binds an array; psycopg 3 adapts a
tuple to a composite instead, so the value arrives as `(2,3,4)` and Postgres
answers `malformed array literal`. The query text is blameless here, which is
why the two halves are one gate: a rule that reads only the SQL sees half the
class, and the half it misses is the half that took mailing lists down.

The fix is `= ANY(%s)` over a **list**. Operator and parameter change together.

**A contract, not a ratchet.** The tree measures zero and there is no reading of
a non-zero value that is acceptable: each one is a statement that cannot execute,
found by whoever runs that code path rather than by anyone reading it.

**Cross-repo.** Both defects this gate was written from lived outside the
community tree -- a cash-basis report in `enterprise` and a comparison wizard in
`agromarin`, the second with thirteen occurrences in one method. Community CI
checks out this repo alone; the siblings pass ``--roots`` to cover their own, the
way ``naming_vocabulary`` and ``mail_hook_keyword_check`` already do.

**What it cannot see.** A query assembled across methods, or parameters built in
one method and executed in another. `l10n_cl`'s clause was appended to a string
that another module executed, and `agromarin`'s parameters were appended to a
list two calls away from the cursor. Following either needs cross-file dataflow;
the literal and the call site are what a single file offers, and between them
they reach every occurrence that is written in one place. Keeping a statement
and its execution together is the practice that makes the rest reachable.

Usage::

  python tooling/architecture/sql_placeholder.py             # report
  python tooling/architecture/sql_placeholder.py --check     # CI
  python tooling/architecture/sql_placeholder.py --count
  python tooling/architecture/sql_placeholder.py --json
  python tooling/architecture/sql_placeholder.py --roots ../enterprise
"""

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

ADR = "unrecorded"

ROOT = find_odoo_root(Path(__file__).resolve(), tool="sql_placeholder")

SCAN_ROOTS = ("addons", "odoo", "tools", "tooling")

# Uppercase `IN` only: "generated in %s seconds" is prose, and a rule that
# cannot tell a sentence from a statement is one nobody keeps.
IN_PLACEHOLDER = re.compile(r"\bIN\s+%(?:\(\w+\))?s")

# Enough of a statement to be sure this is SQL. `AND` earns its place: a clause
# appended to a query built elsewhere carries no other keyword, and that is how
# both defects that reached production were spelled.
SQL_KEYWORD = re.compile(
    r"\b(SELECT|UPDATE|DELETE|INSERT|WHERE|FROM|JOIN|SET|AND|OR)\b"
)

CURSOR_NAMES = frozenset({"cr", "_cr", "cursor"})
EXECUTE_METHODS = frozenset({"execute", "executemany"})


@dataclass(frozen=True)
class Finding:
    kind: str
    path: str
    line: int
    detail: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}  [{self.kind}] {self.detail}"


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _is_test(path: Path) -> bool:
    """A test is a fixture and may take whatever shape it needs.

    `test_db_cursor` passes tuples on purpose -- it is the suite that pins what
    the driver does with one -- and this gate's own tests spell out the defect
    verbatim. Reading either would make the contract unsatisfiable by anything
    except deleting the tests that describe it.
    """
    return any(part == "tests" or part.startswith("test_") for part in path.parts)


def _python_files(roots: list[Path]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        if root.is_file():
            files.append(root)
        elif root.is_dir():
            files.extend(
                p
                for p in root.rglob("*.py")
                if "node_modules" not in p.parts
                and "__pycache__" not in p.parts
                and not _is_test(p)
            )
    return sorted(set(files))


def _exempt_literals(tree: ast.Module) -> set[tuple[int, int]]:
    """Literals the `IN` rule must not read.

    ``SQL()`` arguments, because that spelling rewrites the placeholder; and the
    left operand of ``%``, where Python writes the values into the statement text
    before Postgres sees it -- a CHECK constraint listing what it allows, not a
    bind.
    """
    exempt: set[tuple[int, int]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else getattr(node.func, "attr", "")
            )
            if name == "SQL":
                for inner in ast.walk(node):
                    if isinstance(inner, ast.Constant) and isinstance(inner.value, str):
                        exempt.add((inner.lineno, inner.col_offset))
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
            for inner in ast.walk(node.left):
                if isinstance(inner, ast.Constant) and isinstance(inner.value, str):
                    exempt.add((inner.lineno, inner.col_offset))
    return exempt


def _is_cursor_execute(node: ast.Call) -> bool:
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr not in EXECUTE_METHODS:
        return False
    target = func.value
    name = target.id if isinstance(target, ast.Name) else getattr(target, "attr", "")
    return name in CURSOR_NAMES


def _tuple_values(params: ast.AST) -> list[ast.AST]:
    """Tuple-valued *elements* of a parameter container.

    The container itself is not a finding: ``cr.execute(sql, (a, b))`` and
    ``cr.execute(sql, tuple(values))`` both pass a sequence of parameters, which
    is the calling convention. What cannot work is one parameter that is itself a
    tuple, since no placeholder binds one.
    """
    if isinstance(params, ast.Tuple | ast.List):
        elements = params.elts
    elif isinstance(params, ast.Dict):
        elements = [value for value in params.values if value is not None]
    else:
        return []
    return [
        element
        for element in elements
        if isinstance(element, ast.Tuple)
        or (
            isinstance(element, ast.Call)
            and isinstance(element.func, ast.Name)
            and element.func.id == "tuple"
        )
    ]


def measure(roots: list[Path]) -> tuple[list[Finding], int]:
    findings: list[Finding] = []
    execute_sites = 0
    for path in _python_files(roots):
        try:
            tree = ast.parse(path.read_bytes())
        except SyntaxError, ValueError:
            continue
        exempt = _exempt_literals(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if (node.lineno, node.col_offset) in exempt:
                    continue
                if IN_PLACEHOLDER.search(node.value) and SQL_KEYWORD.search(node.value):
                    findings.append(
                        Finding(
                            "in-placeholder",
                            _rel(path),
                            node.lineno,
                            "`IN %s` binds as `IN $1` -- use `= ANY(%s)` over a list",
                        )
                    )
            elif isinstance(node, ast.Call) and _is_cursor_execute(node):
                execute_sites += 1
                if len(node.args) < 2:
                    continue
                findings.extend(
                    Finding(
                        "tuple-parameter",
                        _rel(path),
                        offender.lineno,
                        "a tuple parameter adapts to a composite, not an array "
                        "-- pass a list",
                    )
                    for offender in _tuple_values(node.args[1])
                )
    return sorted(findings, key=lambda f: (f.path, f.line, f.kind)), execute_sites


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check", action="store_true", help="CI mode: exit 1 on any finding"
    )
    parser.add_argument("--count", action="store_true", help="print the count only")
    parser.add_argument("--json", action="store_true", help="machine-readable")
    parser.add_argument("--roots", nargs="+", help="extra trees to scan")
    args = parser.parse_args(argv)

    roots = [ROOT / r for r in SCAN_ROOTS]
    if args.roots:
        roots += [Path(r).resolve() for r in args.roots]
    findings, execute_sites = measure(roots)

    # Refuse a tree that yielded nothing rather than report a clean zero: an
    # empty scan and a tree with no bad placeholder print the same 0, and only
    # one of them means anything. This fork talks to Postgres directly in
    # hundreds of places, so "no cursor.execute anywhere" is a broken scan by
    # construction.
    if not execute_sites:
        raise SystemExit(
            f"sql_placeholder: no cursor.execute call found under "
            f"{', '.join(_rel(r) for r in roots)} -- the scan found no inputs; "
            "refusing to report 0 findings."
        )

    if args.count:
        print(len(findings))
        return 0
    if args.json:
        print(json.dumps([f.__dict__ for f in findings], indent=2))
        return 1 if (args.check and findings) else 0

    print("SQL placeholders psycopg 3 cannot bind")
    print("=" * 72)
    for finding in findings:
        print(f"  {finding}")
    if not findings:
        print("  every parameter in a raw query is one the driver can bind. ✓")
    print("-" * 72)
    print(f"scanned: {', '.join(_rel(r) for r in roots)}")
    print(f"cursor.execute call sites: {execute_sites}")
    print(f"findings: {len(findings)}")
    if findings:
        print(
            "\nEach one raises the first time that statement runs.\n"
            "Write `= ANY(%s)` and pass a list, or build the query with SQL()."
        )
    return 1 if (args.check and findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())

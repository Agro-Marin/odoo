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

IN_PLACEHOLDER = re.compile(r"\bIN\s+%(?:\(\w+\))?s")

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
    exempt: set[tuple[int, int]] = set()
    for node in ast.walk(tree):
        if isinstance(
            node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
        ):
            first = node.body[0] if node.body else None
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                exempt.add((first.value.lineno, first.value.col_offset))
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
    parser = argparse.ArgumentParser(description=__doc__)
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

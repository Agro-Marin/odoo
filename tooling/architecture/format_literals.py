import argparse
import ast
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

# No record yet. ADRs are a work in progress in this fork and this gate does not
# wait on one; `UNRECORDED_GATES` is where that is declared rather than hidden.
ADR = "unrecorded"

ROOT = find_odoo_root(Path(__file__).resolve(), tool="format_literals")

# A scope that registers a format, a reader or a writer IS the declaration, not
# a restatement of one. `_writer("csv", "text/csv", ROWS, _write_csv)` names the
# writer `csv` and the mimetype it emits; the first is an identifier, not a
# filename extension, and reading it as one made the format layer its own worst
# offender.
DECLARING_CALLS = (
    "Format",
    "register_format",
    "register_extension",
    "register_reader",
    "register_writer",
)

SKIP_DIRS = frozenset({"__pycache__", "node_modules", ".git", "tests", "migrations"})


@dataclass(frozen=True, order=True)
class Finding:
    path: str
    line: int
    scope: str
    mimetype: str
    extension: str

    def __str__(self) -> str:
        return (
            f"{self.path}:{self.line}  {self.scope}  "
            f"states {self.mimetype!r} and .{self.extension}"
        )


def python_files(root: Path):
    for path in sorted(root.rglob("*.py")):
        if SKIP_DIRS & set(path.parts):
            continue
        if path.name.startswith("test_"):
            continue
        yield path


def parse(path: Path) -> ast.Module | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError, UnicodeDecodeError, OSError:
        return None


def declared_formats(roots: list[Path]) -> dict[str, str]:
    """Every registered format, as mimetype -> canonical extension.

    Read from the registrations themselves rather than from a list here, so a
    format added anywhere is a format this gate knows about in the same commit.
    """
    declared: dict[str, str] = {}
    for root in roots:
        for path in python_files(root):
            tree = parse(path)
            if tree is None:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if not isinstance(node.func, ast.Name):
                    continue
                if node.func.id != "Format":
                    continue
                pair = _format_pair(node)
                if pair:
                    declared.setdefault(*pair)
    return declared


def _format_pair(node: ast.Call) -> tuple[str, str] | None:
    values: dict[str, str] = {}
    for name, argument in zip(("mimetype", "extension"), node.args, strict=False):
        if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
            values[name] = argument.value
    for keyword in node.keywords:
        if keyword.arg in ("mimetype", "extension"):
            if isinstance(keyword.value, ast.Constant):
                if isinstance(keyword.value.value, str):
                    values[keyword.arg] = keyword.value.value
    if "mimetype" in values and "extension" in values:
        return values["mimetype"], values["extension"]
    return None


def _relative(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _strings(node: ast.AST):
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            yield child


def _names_the_extension(text: str, extension: str) -> bool:
    """Whether a literal states a filename extension rather than mentioning it.

    `".csv"`, `"csv"` and `"report.csv"` do; a mimetype containing the word, or
    a sentence, does not. Kept deliberately narrow: the gate is looking for a
    place that decided the SAME format twice, and a loose match here turns an
    `Accept:` header into a finding.
    """
    if "/" in text:
        return False
    stripped = text.lstrip(".")
    return stripped == extension or text.endswith(f".{extension}")


def measure(roots: list[Path]) -> list[Finding]:
    declared = declared_formats(roots)
    if not declared:
        raise RuntimeError(
            "no Format registration found in the scanned roots; the scan is "
            "measuring nothing rather than finding nothing"
        )
    found: list[Finding] = []
    for root in roots:
        for path in python_files(root):
            tree = parse(path)
            if tree is None:
                continue
            relative = _relative(path)
            for scope in _scopes(tree):
                declaring = any(
                    isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Name)
                    and n.func.id in DECLARING_CALLS
                    for n in ast.walk(scope.node)
                )
                if declaring:
                    continue
                literals = list(_strings(scope.node))
                for mimetype, extension in declared.items():
                    stated = [s for s in literals if s.value == mimetype]
                    if not stated:
                        continue
                    if not any(
                        _names_the_extension(s.value, extension) for s in literals
                    ):
                        continue
                    found.append(
                        Finding(
                            relative,
                            min(s.lineno for s in stated),
                            scope.name,
                            mimetype,
                            extension,
                        )
                    )
    return sorted(found)


@dataclass(frozen=True)
class Scope:
    name: str
    node: ast.AST


def _scopes(tree: ast.Module) -> list[Scope]:
    """Every function, plus the module body outside them.

    A function is the unit because deciding a format twice is a decision made in
    one place; two unrelated functions in a file that happen to name a mimetype
    and an extension are not restating each other.
    """
    scopes = [
        Scope(node.name, node)
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    module_level = ast.Module(
        body=[
            n for n in tree.body if not isinstance(n, (ast.FunctionDef, ast.ClassDef))
        ],
        type_ignores=[],
    )
    scopes.append(Scope("<module>", module_level))
    return scopes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", action="store_true", help="print the count only")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--top", type=int, default=20, help="offenders to list (0 = all)"
    )
    parser.add_argument(
        "roots",
        nargs="*",
        default=None,
        help="directories to scan (default: this repo's odoo/ and addons/)",
    )
    args = parser.parse_args(argv)

    roots = (
        [Path(r).resolve() for r in args.roots]
        if args.roots
        else [ROOT / "odoo", ROOT / "addons"]
    )
    try:
        found = measure(roots)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.count:
        print(len(found))
        return 0
    if args.json:
        print(json.dumps([asdict(f) for f in found], indent=2))
        return 0

    print("Places that decide a declared format's mimetype AND its extension")
    print("=" * 72)
    shown = found if args.top == 0 else found[: args.top]
    for item in shown:
        print(item)
    if len(found) > len(shown):
        print(f"  ... and {len(found) - len(shown)} more (--top 0 for all)")
    print("-" * 72)
    print(f"\n{len(found)} place(s) restating a declared format")
    print("\nRatchet this number:")
    print("  python tooling/architecture/format_literals.py --count \\")
    print("      | xargs python tooling/ratchet/ratchet.py format_literals --count")
    return 0


if __name__ == "__main__":
    sys.exit(main())

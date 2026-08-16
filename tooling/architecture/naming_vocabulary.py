from __future__ import annotations

import argparse
import ast
import collections
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

ADR = "0033"

ROOT = find_odoo_root(Path(__file__).resolve())
SCAN_ROOTS = ("odoo", "addons")

SKIP_DIRS = frozenset(
    {".git", "node_modules", "__pycache__", ".mypy_cache", "static", "lib", "vendored"}
)

PAYLOAD_SUFFIXES = (
    "_vals",
    "_values",
    "_data",
    "_dict",
    "_domain",
    "_context",
    "_defaults",
    "_list",
    "_args",
    "_params",
)

ABOLISHED: dict[str, tuple[str, bool]] = {
    "build": ("_prepare_", True),
    "make": ("_prepare_", True),
    "compose": ("_prepare_", True),
    "construct": ("_prepare_", True),
    "fetch": ("_get_", False),
    "retrieve": ("_get_", False),
    "obtain": ("_get_", False),
    "lookup": ("_get_", False),
    "validate": ("_check_", False),
    "verify": ("_check_", False),
    "ensure": ("_check_", False),
    "control": ("_check_", False),
    "assign": ("_update_", False),
    "fill": ("_update_", False),
    "inject": ("_update_", False),
    "append": ("_add_", False),
    "delete": ("_remove_", False),
    "purge": ("_remove_", False),
}

RESERVED = {
    "drop": "SQL DDL",
    "insert": "SQL DML",
    "push": "stack / queue",
    "discard": "set.discard — remove if present, never raise",
}


@dataclass(frozen=True)
class Violation:
    path: str
    line: int
    name: str
    verb: str
    canonical: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}  {self.name}  ->  {self.canonical}*"


def classify(name: str) -> tuple[str, str] | None:
    if name.startswith("__") and name.endswith("__"):
        return None
    stem = name.lstrip("_")
    verb, _, rest = stem.partition("_")
    if not rest:
        return None
    entry = ABOLISHED.get(verb)
    if entry is None:
        return None
    canonical, payload_only = entry
    if payload_only and not name.endswith(PAYLOAD_SUFFIXES):
        return None
    return verb, canonical


MODEL_BASES = frozenset({"Model", "TransientModel", "AbstractModel", "BaseModel"})


def is_model_class(node: ast.ClassDef) -> bool:

    for base in node.bases:
        name = base.attr if isinstance(base, ast.Attribute) else getattr(base, "id", "")
        if name in MODEL_BASES:
            return True
    return any(
        isinstance(stmt, ast.Assign)
        and any(
            isinstance(t, ast.Name) and t.id in ("_name", "_inherit")
            for t in stmt.targets
        )
        for stmt in node.body
    )


def _python_files(roots: list[Path]) -> list[Path]:
    found: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*.py"):
            parts = set(path.parts)
            if parts & SKIP_DIRS:
                continue
            if "tests" in parts or path.name.startswith("test_"):
                continue
            found.append(path)
    return found


def _display(path: Path) -> Path:
    try:
        return path.relative_to(ROOT)
    except ValueError:
        return path


def measure(roots: list[Path] | None = None) -> list[Violation]:

    roots = roots or [ROOT / r for r in SCAN_ROOTS]
    files = _python_files(roots)
    if not files:
        raise RuntimeError(
            f"no Python files under {', '.join(str(r) for r in roots)} — "
            f"refusing to report a count from an empty scan"
        )

    out: list[Violation] = []
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError, UnicodeDecodeError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef) or not is_model_class(node):
                continue
            for item in node.body:
                if not isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                    continue
                hit = classify(item.name)
                if hit is None:
                    continue
                out.append(
                    Violation(
                        path=str(_display(path)),
                        line=item.lineno,
                        name=item.name,
                        verb=hit[0],
                        canonical=hit[1],
                    )
                )
    out.sort(key=lambda v: (v.path, v.line))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", action="store_true", help="print the count only")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--verb", help="restrict the report to one abolished verb")
    parser.add_argument(
        "--roots", nargs="+", help="scan these paths instead of odoo/ and addons/"
    )
    parser.add_argument(
        "--top", type=int, default=20, help="offenders to list (0 = all)"
    )
    args = parser.parse_args(argv)

    roots = [Path(r).resolve() for r in args.roots] if args.roots else None
    try:
        found = measure(roots)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.verb:
        found = [v for v in found if v.verb == args.verb]

    if args.count:
        print(len(found))
        return 0
    if args.json:
        print(json.dumps([asdict(v) for v in found], indent=2))
        return 0

    print("Method-naming vocabulary (§2.4 abolished verbs)")
    print("=" * 72)
    shown = found if args.top == 0 else found[: args.top]
    for item in shown:
        print(f"  {item}")
    if len(found) > len(shown):
        print(f"  ... and {len(found) - len(shown)} more (--top 0 for all)")
    print("-" * 72)

    by_verb = collections.Counter(v.verb for v in found)
    by_canon: collections.Counter[str] = collections.Counter()
    for v in found:
        by_canon[v.canonical] += 1
    print(f"\n{len(found)} definition(s) using an abolished verb\n")
    print("  by canonical target:")
    for canon, n in by_canon.most_common():
        verbs = sorted({v.verb for v in found if v.canonical == canon})
        print(f"    {canon + '*':<12}{n:>5}   from {', '.join(verbs)}")
    print("\n  by verb:")
    for verb, n in by_verb.most_common():
        print(f"    _{verb}_{'':<8}{n:>5}")

    print("\nRatchet this number:")
    print("  python tooling/architecture/naming_vocabulary.py --count \\")
    print("      | xargs python tooling/ratchet/ratchet.py naming --count")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

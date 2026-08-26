#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import collections
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _sources
from _repo_root import find_odoo_root

ADR = "unrecorded"

ROOT = find_odoo_root(Path(__file__).resolve(), tool="compute_context_deps")
SCAN_ROOTS = ("odoo", "addons")

ENV_READS = {
    "uid": ("user", "uid"),
}
CALL_READS = {
    "guest": ("_get_guest_from_context",),
    "lang": (
        "get_lang",
        "format_amount",
        "format_date",
        "format_datetime",
        "format_list",
        "_description_selection",
    ),
}

KEY_ONLY_WRAPPERS = ("list", "keys", "tuple", "set", "sorted")


@dataclass(frozen=True)
class Violation:
    file: str
    line: int
    method: str
    key: str

    def __str__(self) -> str:
        return f"{self.key:<8} {self.file}:{self.line}  {self.method}"


def _python_files(roots: list[Path]) -> list[Path]:
    return sorted(
        p
        for root in roots
        for p in root.rglob("*.py")
        if "__pycache__" not in p.parts and not _sources.is_test_path(p)
    )


def declared_keys(node: ast.FunctionDef) -> set[str]:
    keys: set[str] = set()
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        func = decorator.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name != "depends_context":
            continue
        for arg in decorator.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                keys.add(arg.value)
    return keys


def _parents(node: ast.FunctionDef) -> dict[ast.AST, ast.AST]:
    return {
        child: parent
        for parent in ast.walk(node)
        for child in ast.iter_child_nodes(parent)
    }


def _reads_labels(call: ast.Call, parents: dict[ast.AST, ast.AST]) -> bool:
    wrapper = parents.get(call)
    if not (isinstance(wrapper, ast.Call) and _called_name(wrapper) == "dict"):
        return True
    outer = parents.get(wrapper)
    if isinstance(outer, ast.Call) and _called_name(outer) in KEY_ONLY_WRAPPERS:
        return False
    return not (isinstance(outer, ast.Attribute) and outer.attr in KEY_ONLY_WRAPPERS)


def _called_name(call: ast.Call) -> str:
    func = call.func
    return func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")


def read_keys(node: ast.FunctionDef) -> set[str]:
    keys: set[str] = set()
    parents = _parents(node)
    for sub in ast.walk(node):
        if isinstance(sub, ast.Attribute):
            value = sub.value
            reads_env = (isinstance(value, ast.Attribute) and value.attr == "env") or (
                isinstance(value, ast.Name) and value.id == "env"
            )
            if reads_env:
                for key, attrs in ENV_READS.items():
                    if sub.attr in attrs:
                        keys.add(key)
        elif isinstance(sub, ast.Call):
            called = _called_name(sub)
            for key, names in CALL_READS.items():
                if called not in names:
                    continue
                if called == "_description_selection" and not _reads_labels(
                    sub, parents
                ):
                    continue
                keys.add(key)
    return keys


def measure(roots: list[Path] | None = None) -> list[Violation]:
    roots = roots or [ROOT / r for r in SCAN_ROOTS]
    files = _python_files(roots)
    if not files:
        raise RuntimeError(
            f"no Python files under {', '.join(str(r) for r in roots)} — "
            f"refusing to report a count from an empty scan"
        )

    found: list[Violation] = []
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError, UnicodeDecodeError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            if not node.name.startswith("_compute_"):
                continue
            missing = read_keys(node) - declared_keys(node)
            found.extend(
                Violation(_sources.display(path, ROOT), node.lineno, node.name, key)
                for key in sorted(missing)
            )
    return sorted(found, key=lambda v: (v.key, v.file, v.line))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", action="store_true", help="print the count only")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--key", help="restrict the report to one context key")
    parser.add_argument(
        "--roots", nargs="+", help="scan these paths instead of odoo/ and addons/"
    )
    parser.add_argument(
        "--top", type=int, default=30, help="offenders to list (0 = all)"
    )
    args = parser.parse_args(argv)

    roots = [Path(r).resolve() for r in args.roots] if args.roots else None
    try:
        found = measure(roots)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.key:
        found = [v for v in found if v.key == args.key]

    if args.count:
        print(len(found))
        return 0
    if args.json:
        print(json.dumps([asdict(v) for v in found], indent=2))
        return 0

    print("Computes reading context they do not declare (@api.depends_context)")
    print("=" * 72)
    shown = found if args.top == 0 else found[: args.top]
    for item in shown:
        print(f"  {item}")
    if len(found) > len(shown):
        print(f"  ... and {len(found) - len(shown)} more (--top 0 for all)")
    print("-" * 72)

    by_key = collections.Counter(v.key for v in found)
    print(f"\n{len(found)} undeclared context read(s)\n")
    for key, n in by_key.most_common():
        print(f"    {key:<10}{n:>5}")

    print("\nRatchet this number:")
    print("  python tooling/architecture/compute_context_deps.py --count \\")
    print("      | xargs python tooling/ratchet/ratchet.py computectx --count")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

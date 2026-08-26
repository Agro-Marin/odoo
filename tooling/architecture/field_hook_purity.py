from __future__ import annotations

import argparse
import ast
import collections
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import _ast_cache
import _sources
import field_hook_naming as fh
import naming_vocabulary as nv
from _repo_root import find_odoo_root

ADR = "0051"

ROOT = find_odoo_root(Path(__file__).resolve())


@dataclass(frozen=True)
class Violation:
    path: str
    line: int
    model: str
    method: str
    attrs: str
    calls: int

    def __str__(self) -> str:
        return (
            f"{self.path}:{self.line}  {self.model}.{self.method}  serves "
            f"{self.attrs}= and is called on self {self.calls}x in production code"
        )


def _test_files(roots: list[Path]) -> list[Path]:
    found = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*.py"):
            parts = set(path.parts)
            if parts & nv.SKIP_DIRS:
                continue
            if "tests" in parts or path.name.startswith("test_"):
                found.append(path)
    return found


def _note_declaration(
    statement: ast.stmt, model: str, reached_by: dict[tuple[str, str], set[str]]
) -> None:
    if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
        return
    call = statement.value
    if not isinstance(call, ast.Call):
        return
    func = call.func
    if not (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id == "fields"
    ):
        return
    for keyword in call.keywords:
        if keyword.arg not in fh.ATTRS:
            continue
        method = fh._hook_name(keyword.arg, keyword.value)
        if method:
            reached_by[model, method].add(
                "lambda" if isinstance(keyword.value, ast.Lambda) else "direct"
            )


def measure(roots: list[Path] | None = None) -> list[Violation]:
    roots = roots or [ROOT / r for r in nv.SCAN_ROOTS]
    production = nv._python_files(roots)
    if not production:
        raise RuntimeError(
            f"no Python files under {', '.join(str(r) for r in roots)} — "
            f"refusing to report a count from an empty scan"
        )

    hooks: dict[tuple[str, str], set[str]] = collections.defaultdict(set)
    where: dict[tuple[str, str], tuple[str, int]] = {}
    calls: collections.Counter[tuple[str, str]] = collections.Counter()
    reached_by: dict[tuple[str, str], set[str]] = collections.defaultdict(set)
    served: dict[tuple[str, str], set[str]] = collections.defaultdict(set)
    hooking: dict[tuple[str, str], set[str]] = collections.defaultdict(set)
    callers: dict[tuple[str, str], set[str]] = collections.defaultdict(set)

    for path in production:
        try:
            tree = _ast_cache.parse_file(path)
        except SyntaxError, UnicodeDecodeError:
            continue
        display = _sources.display(path, ROOT)
        for model, attr, method, field, line in fh._field_hooks(tree):
            hooks[model, method].add(attr)
            served[model, method].add(field)
            hooking[model, field].add(method)
            where.setdefault((model, method), (display, line))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef) or not nv.is_model_class(node):
                continue
            model = fh._model_of(node) or "?"
            for statement in node.body:
                if not isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef):
                    _note_declaration(statement, model, reached_by)
                    continue
                for sub in ast.walk(statement):
                    if (
                        isinstance(sub, ast.Call)
                        and isinstance(sub.func, ast.Attribute)
                        and isinstance(sub.func.value, ast.Name)
                        and sub.func.value.id == "self"
                    ):
                        calls[model, sub.func.attr] += 1
                        callers[model, sub.func.attr].add(statement.name)

    out = []
    for key, attrs in hooks.items():
        if not calls[key]:
            continue
        if reached_by[key] == {"lambda"}:
            continue
        siblings = {h for field in served[key] for h in hooking[key[0], field]}
        if callers[key] <= siblings:
            continue
        out.append(
            Violation(*where[key], key[0], key[1], "/".join(sorted(attrs)), calls[key])
        )
    out.sort(key=lambda v: (-v.calls, v.path, v.method))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", action="store_true", help="print the count only")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--roots", nargs="+", help="scan these paths instead")
    parser.add_argument("--top", type=int, default=20, help="offenders to list")
    args = parser.parse_args(argv)

    roots = [Path(r).resolve() for r in args.roots] if args.roots else None
    try:
        found = measure(roots)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.count:
        print(len(found))
        return 0
    if args.json:
        print(json.dumps([asdict(v) for v in found], indent=2))
        return 0

    print("Field-hook purity (ADR-0051: a hook does one job)")
    print("=" * 72)
    shown = found if args.top == 0 else found[: args.top]
    for item in shown:
        print(f"  {item}")
    if len(found) > len(shown):
        print(f"  ... and {len(found) - len(shown)} more (--top 0 for all)")
    print("-" * 72)

    by_attr: collections.Counter[str] = collections.Counter()
    for item in found:
        for attr in item.attrs.split("/"):
            by_attr[attr] += 1
    print(f"\n{len(found)} hook(s) that production code also calls\n")
    print("  by attribute:")
    for attr, n in by_attr.most_common():
        print(f"    {attr + '=':<12}{n:>5}")

    print("\nRatchet this number:")
    print("  python tooling/architecture/field_hook_purity.py --count \\")
    print("      | xargs python tooling/ratchet/ratchet.py hookpurity --count")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

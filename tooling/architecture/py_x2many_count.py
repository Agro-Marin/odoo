#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _sources
from _repo_root import find_odoo_root, sibling_repos_root

ADR = "0052"

ROOT = find_odoo_root(Path(__file__).resolve(), tool="py_x2many_count")

SCOPE = ROOT / "odoo"

DEFAULT_ADDON = "core"

ALL_ADDONS = "addons"

SIBLING_SCOPES = ("enterprise", "agromarin")

GOVERNED_ADDONS = (
    DEFAULT_ADDON,
    ALL_ADDONS,
    "mail",
    "account",
    "stock",
    "project",
    *SIBLING_SCOPES,
)

RELATIONAL_SUFFIX = "_ids"


def addon_src(addon: str = DEFAULT_ADDON) -> Path:
    if addon == DEFAULT_ADDON:
        return SCOPE
    if addon == ALL_ADDONS:
        return ROOT / "addons"
    if addon in SIBLING_SCOPES:
        return sibling_repos_root(ROOT) / addon
    return ROOT / "addons" / addon


@dataclass(frozen=True)
class HandCount:
    file: str
    line: int
    kind: str
    what: str

    def __str__(self) -> str:
        return f"  {self.kind:12}  {self.file}:{self.line}  {self.what}"


def iter_source_files(src: Path | None = None) -> list[Path]:
    return sorted(
        p
        for p in (SCOPE if src is None else src).rglob("*.py")
        if "__pycache__" not in p.parts and not _sources.is_test_path(p)
    )


def _counter_assignment(node: ast.AST) -> str | None:
    if not (isinstance(node, ast.Assign) and len(node.targets) == 1):
        return None
    target, value = node.targets[0], node.value
    if not (isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name)):
        return None
    if not (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Name)
        and value.func.id == "len"
        and len(value.args) == 1
    ):
        return None
    arg = value.args[0]
    if not (isinstance(arg, ast.Attribute) and isinstance(arg.value, ast.Name)):
        return None
    if arg.value.id != target.value.id:
        return None
    return arg.attr if arg.attr.endswith(RELATIONAL_SUFFIX) else None


def _guards_unsaved(test: ast.AST) -> bool:
    src = ast.unparse(test)
    return "self._ids" in src or "NewId" in src


def _loops_over_self(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.For)
        and isinstance(node.iter, ast.Name)
        and node.iter.id == "self"
    )


def measure(
    files: list[Path] | None = None,
    src: Path | None = None,
) -> list[HandCount]:
    if files is None:
        files = iter_source_files(src)
        if not files:
            raise RuntimeError(
                f"no Python sources under {SCOPE if src is None else src} -- the "
                f"scan found nothing, which is not the same as finding nothing wrong"
            )
    found: list[HandCount] = []
    for path in files:
        try:
            tree = ast.parse(path.read_bytes())
        except SyntaxError:
            continue
        display = _sources.display(path, ROOT)
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not fn.name.startswith("_compute"):
                continue
            stack: list[tuple[ast.AST, bool]] = [(fn, False)]
            while stack:
                node, unsaved = stack.pop()
                for child in ast.iter_child_nodes(node):
                    child_unsaved = unsaved or (
                        isinstance(node, ast.If)
                        and child in node.body
                        and _guards_unsaved(node.test)
                    )
                    if (
                        field := _counter_assignment(child)
                    ) is not None and not child_unsaved:
                        found.append(
                            HandCount(
                                display, child.lineno, "len", f"{fn.name} -> {field}"
                            )
                        )
                    stack.append((child, child_unsaved))
            for node in ast.walk(fn):
                if not _loops_over_self(node):
                    continue
                found.extend(
                    HandCount(display, inner.lineno, "search_count", fn.name)
                    for inner in ast.walk(node)
                    if isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Attribute)
                    and inner.func.attr == "search_count"
                )
    found.sort(key=lambda f: (f.file, f.line))
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", action="store_true", help="print the count only")
    parser.add_argument("--json", action="store_true", help="machine-readable")
    parser.add_argument("--top", type=int, default=25, help="0 for all")
    parser.add_argument(
        "--addon",
        default=DEFAULT_ADDON,
        help=(
            f"what to measure: {DEFAULT_ADDON} (default) is the odoo/ package, "
            f"{ALL_ADDONS} is the whole bundled-addons tree as one number, "
            f"{' and '.join(SIBLING_SCOPES)} are sibling checkouts, and "
            f"anything else is that one module under addons/"
        ),
    )
    args = parser.parse_args(argv)

    if args.addon not in GOVERNED_ADDONS:
        print(
            f"error: {args.addon!r} is not a governed scope. Onboarding one is a "
            f"row in GOVERNED_ADDONS and its own baseline, not a flag: a floor "
            f"over an unscanned tree checks nothing.\n"
            f"       governed: {', '.join(GOVERNED_ADDONS)}",
            file=sys.stderr,
        )
        return 2

    src = addon_src(args.addon)
    if args.addon in SIBLING_SCOPES and not src.is_dir():
        print(
            f"SKIP: {args.addon} is not checked out beside {ROOT.name}; "
            f"its own architecture.yml pairs the two and runs this there.",
            file=sys.stderr,
        )
        return 0

    try:
        found = measure(src=src)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.count:
        print(len(found))
        return 0
    if args.json:
        print(json.dumps([asdict(f) for f in found], indent=2))
        return 0

    where = {DEFAULT_ADDON: "odoo/", ALL_ADDONS: "addons/"}.get(
        args.addon,
        f"{args.addon}/" if args.addon in SIBLING_SCOPES else f"addons/{args.addon}/",
    )
    print(f"Counters that count by hand (ADR-0052, {where})")
    print("=" * 72)
    shown = found if args.top == 0 else found[: args.top]
    for item in shown:
        print(item)
    if len(found) > len(shown):
        print(f"  ... and {len(found) - len(shown)} more (--top 0 for all)")
    print("-" * 72)
    by_kind = {k: sum(1 for f in found if f.kind == k) for k in ("len", "search_count")}
    print(f"\n{len(found)} counter(s)   <- the ratcheted number")
    print(
        f"  len(x2many): {by_kind['len']}   search_count in a loop: {by_kind['search_count']}"
    )
    suffix = "" if args.addon == DEFAULT_ADDON else f" --addon {args.addon}"
    name = (
        "py_x2many_count"
        if args.addon == DEFAULT_ADDON
        else f"py_x2many_count_{args.addon}"
    )
    print("\nRatchet it:")
    print(f"  python tooling/architecture/py_x2many_count.py --count{suffix} \\")
    print(f"      | xargs python tooling/ratchet/ratchet.py {name} --count")
    return 0


if __name__ == "__main__":
    sys.exit(main())

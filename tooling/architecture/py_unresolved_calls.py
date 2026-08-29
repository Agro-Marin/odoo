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
from _repo_root import find_odoo_root

ADR = "0058"

ROOT = find_odoo_root(Path(__file__).resolve(), tool="py_unresolved_calls")

SCOPES = (ROOT / "odoo", ROOT / "addons")

EXTERNAL: frozenset[str] = frozenset(
    {
        "_add_object",
        "_ansi_style",
        "_asdict",
        "_build_localename",
        "_create_stdlib_context",
        "_current_frames",
        "_exit",
        "_formatMessage",
        "_getframe",
        "_load_region",
        "_removeTestAtIndex",
    }
)


_ATTR_BUILTINS = frozenset({"getattr", "hasattr", "setattr", "delattr"})


def _names_a_string_binds(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Call):
        func = node.func
        name = (
            func.id
            if isinstance(func, ast.Name)
            else func.attr
            if isinstance(func, ast.Attribute)
            else ""
        )
        if name in _ATTR_BUILTINS or name in {f"__{n}__" for n in _ATTR_BUILTINS}:
            return {
                arg.value
                for arg in node.args[1:2]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
            }
        return set()
    if isinstance(node, ast.Assign) and any(
        isinstance(t, ast.Name) and t.id == "__slots__" for t in node.targets
    ):
        return {
            elt.value
            for elt in getattr(node.value, "elts", [])
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
        }
    return set()


EXTERNAL_BY_ROOT: dict[str, frozenset[str]] = {
    "enterprise": frozenset(
        {
            "_make_sign_key",
            "_make_verify_key",
            "_sign_node",
        }
    ),
}


@dataclass(frozen=True)
class UnresolvedCall:
    file: str
    line: int
    name: str
    source: str

    def __str__(self) -> str:
        return f"  {self.file}:{self.line}  {self.name}\n      {self.source}"


def iter_source_files(scopes: tuple[Path, ...] = SCOPES) -> list[Path]:
    return sorted(
        p
        for scope in scopes
        for p in scope.rglob("*.py")
        if "__pycache__" not in p.parts
    )


def measure(
    scopes: tuple[Path, ...] = SCOPES,
    report_scopes: tuple[Path, ...] | None = None,
    external: frozenset[str] = EXTERNAL,
) -> list[UnresolvedCall]:
    files = iter_source_files(scopes)
    if not files:
        raise RuntimeError(
            f"no Python sources under {', '.join(str(s) for s in scopes)} -- the "
            f"scan found nothing, which is not the same as finding nothing wrong"
        )

    defined: set[str] = set()
    bound: set[str] = set()
    calls: list[tuple[Path, ast.Call, str]] = []
    trees: list[tuple[Path, ast.Module, list[str]]] = []

    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        trees.append((path, tree, text.splitlines()))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                defined.add(node.name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Attribute):
                        bound.add(target.attr)
                    elif isinstance(target, ast.Name):
                        bound.add(target.id)
            elif isinstance(node, ast.AnnAssign) and isinstance(
                node.target, ast.Attribute
            ):
                bound.add(node.target.attr)
            bound.update(_names_a_string_binds(node))

    for path, tree, lines in trees:
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(
                node.func, ast.Attribute
            ):
                continue
            name = node.func.attr
            if not name.startswith("_") or name.startswith("__"):
                continue
            calls.append((path, node, lines[node.lineno - 1].strip()))

    def reported(path: Path) -> bool:
        return report_scopes is None or any(
            path.is_relative_to(scope) for scope in report_scopes
        )

    found = [
        UnresolvedCall(
            _sources.display(path, ROOT), node.lineno, node.func.attr, source
        )
        for path, node, source in calls
        if node.func.attr not in defined
        and node.func.attr not in bound
        and node.func.attr not in external
        and reported(path)
    ]
    found.sort(key=lambda c: (c.name, c.file, c.line))
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", action="store_true", help="print the count only")
    parser.add_argument("--json", action="store_true", help="machine-readable")
    parser.add_argument("--top", type=int, default=30, help="0 for all")
    parser.add_argument(
        "--also-define",
        nargs="+",
        metavar="PATH",
        help="read these paths for definitions but never report their call "
        "sites. A sibling repository whose CI lane cannot check out the "
        "repositories it depends on measures a count inflated by that "
        "blindness; this reproduces the true reading locally. It is NOT what "
        "the floor measures -- the workflow command is.",
    )
    parser.add_argument(
        "--roots",
        nargs="+",
        help="report calls from these paths instead of odoo/ and addons/; the "
        "definitions of odoo/ and addons/ still count as resolving a name, so a "
        "sibling repository is measured against the framework it runs on",
    )
    args = parser.parse_args(argv)

    def resolved(paths: list[str], flag: str) -> tuple[Path, ...]:
        out = []
        for raw in paths:
            path = Path(raw).resolve()
            if not path.is_dir():
                msg = f"{flag} {raw}: not a directory (resolved to {path})"
                raise RuntimeError(msg)
            if not any(p for p in path.rglob("*.py") if "__pycache__" not in p.parts):
                msg = f"{flag} {raw}: no Python sources under {path}"
                raise RuntimeError(msg)
            out.append(path)
        return tuple(out)

    report_scopes = None
    scopes = SCOPES
    external = EXTERNAL
    try:
        if args.roots:
            report_scopes = resolved(args.roots, "--roots")
            scopes = SCOPES + report_scopes
            for scope in report_scopes:
                external |= EXTERNAL_BY_ROOT.get(scope.name, frozenset())
        if args.also_define:
            scopes += resolved(args.also_define, "--also-define")
            if report_scopes is None:
                report_scopes = SCOPES
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        found = measure(scopes, report_scopes, external)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.count:
        print(len(found))
        return 0
    if args.json:
        print(json.dumps([asdict(c) for c in found], indent=2))
        return 0

    print("Calls to methods this checkout defines nowhere (ADR-0058)")
    print("=" * 72)
    shown = found if args.top == 0 else found[: args.top]
    for item in shown:
        print(item)
    if len(found) > len(shown):
        print(f"  ... and {len(found) - len(shown)} more (--top 0 for all)")
    print("-" * 72)
    names = sorted({c.name for c in found})
    print(f"\n{len(found)} call site(s) over {len(names)} name(s)")
    print(f"  {len(external)} name(s) allowed as external, see EXTERNAL")
    gate = "unresolved_calls"
    flag = ""
    if args.roots:
        gate = f"{gate}_{report_scopes[0].name}"
        flag = f" --roots {' '.join(args.roots)}"
    print("\nRatchet it:")
    print(f"  python tooling/architecture/py_unresolved_calls.py{flag} --count \\")
    print(f"      | xargs python tooling/ratchet/ratchet.py {gate} --count")
    return 0


if __name__ == "__main__":
    sys.exit(main())

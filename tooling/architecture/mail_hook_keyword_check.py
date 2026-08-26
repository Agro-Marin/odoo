import argparse
import ast
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

ADR = "unrecorded"

ROOT = find_odoo_root(Path(__file__).resolve(), tool="mail_hook_keyword_check")

FRAMEWORK_DIR = Path("addons/mail/models")

FRAMEWORK_CALLER_DIR = Path("addons/mail")

HOOK_PREFIXES = ("_notify", "_message", "_mail_", "_track")

SCAN_ROOTS = ("addons", "odoo/addons")


@dataclass(frozen=True)
class Finding:
    hook: str
    path: str
    line: int
    missing: tuple[str, ...]

    def __str__(self) -> str:
        kws = ", ".join(self.missing)
        return f"{self.path}:{self.line}  {self.hook}() cannot accept {kws}"


def _python_files(roots: list[Path]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        if root.is_file():
            files.append(root)
        elif root.is_dir():
            files.extend(p for p in root.rglob("*.py") if "node_modules" not in p.parts)
    return sorted(files)


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _params(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    a = fn.args
    return {x.arg for x in a.posonlyargs + a.args + a.kwonlyargs}


def _methods(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for fn in node.body:
                if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    yield fn


def measure(
    roots: list[Path] | None = None,
    *,
    framework_dir: Path | None = None,
    caller_dir: Path | None = None,
) -> list[Finding]:
    roots = roots or [ROOT / r for r in SCAN_ROOTS]
    framework_dir = framework_dir or ROOT / FRAMEWORK_DIR
    caller_dir = caller_dir or ROOT / FRAMEWORK_CALLER_DIR

    trees: dict[Path, ast.AST] = {}
    for path in _python_files(roots):
        try:
            trees[path] = ast.parse(path.read_text(errors="ignore"))
        except SyntaxError:
            continue

    base_hooks: dict[str, set[str]] = defaultdict(set)
    overrides: dict[str, list[tuple[Path, int, set[str], bool]]] = defaultdict(list)
    for path, tree in trees.items():
        in_framework = path.is_relative_to(framework_dir)
        for fn in _methods(tree):
            if not fn.name.startswith(HOOK_PREFIXES):
                continue
            if in_framework:
                base_hooks[fn.name] |= _params(fn)
            overrides[fn.name].append(
                (path, fn.lineno, _params(fn), fn.args.kwarg is not None)
            )

    if not base_hooks:
        raise SystemExit(
            f"mail_hook_keyword_check: no hooks found under {_rel(framework_dir)} — "
            "the scan found no inputs; refusing to report 0 findings."
        )

    keywords: dict[str, set[str]] = defaultdict(set)
    for path, tree in trees.items():
        if not path.is_relative_to(caller_dir):
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in base_hooks
            ):
                keywords[node.func.attr].update(
                    kw.arg for kw in node.keywords if kw.arg
                )

    if not any(keywords.values()):
        raise SystemExit(
            f"mail_hook_keyword_check: {_rel(caller_dir)} passes no keyword to any "
            "of its own hooks; refusing to report 0 findings."
        )

    findings: list[Finding] = []
    for hook, declared in base_hooks.items():
        used = keywords.get(hook, set()) & declared
        if not used:
            continue
        for path, line, params, absorbs in overrides.get(hook, ()):
            if absorbs or "tests" in path.parts:
                continue
            missing = used - params
            if missing:
                findings.append(Finding(hook, _rel(path), line, tuple(sorted(missing))))
    return sorted(findings, key=lambda f: (f.path, f.line, f.hook))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="CI mode: exit 1 on any finding"
    )
    parser.add_argument("--count", action="store_true", help="print the count only")
    parser.add_argument("--json", action="store_true", help="machine-readable")
    parser.add_argument("--roots", nargs="+", help="extra trees to scan for overrides")
    args = parser.parse_args(argv)

    roots = [ROOT / r for r in SCAN_ROOTS]
    if args.roots:
        roots += [Path(r).resolve() for r in args.roots]
    findings = measure(roots)

    if args.count:
        print(len(findings))
        return 0
    if args.json:
        print(json.dumps([f.__dict__ for f in findings], indent=2, default=list))
        return 1 if (args.check and findings) else 0

    print("mail hook keyword surface")
    print("=" * 72)
    for finding in findings:
        print(f"  {finding}")
    if not findings:
        print("  every override of a mail hook accepts the keywords mail passes it. ✓")
    print("-" * 72)
    print(f"scanned: {', '.join(_rel(r) for r in roots)}")
    print(f"findings: {len(findings)}")
    if findings:
        print(
            "\nEach one raises TypeError the first time that model is notified.\n"
            "Add the parameter to the override and forward it to super()."
        )
    return 1 if (args.check and findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _count_gate
import _sources
from _repo_root import find_odoo_root, sibling_repos_root

ADR = "0077"

ROOT = find_odoo_root(Path(__file__).resolve(), tool="py_hook_arity")

SCOPE = ROOT / "odoo"

DEFAULT_ADDON = "core"

ALL_ADDONS = "addons"

TESTS = "tests"

SIBLING_SCOPES = ("enterprise", "agromarin", "design-themes")

# Measurable with --addon, but not floored here: no workflow in this repository
# drives a sibling checkout, and a baseline nothing drives is a baseline nobody
# reads. Onboard one the way naming_enterprise is, from the sibling's own lane.

GOVERNED_ADDONS = (DEFAULT_ADDON, ALL_ADDONS, TESTS, *SIBLING_SCOPES)

# The ORM invokes each of these with no arguments: it calls the bound method on
# a recordset and passes nothing. A parameter beyond `self` therefore cannot be
# supplied by the framework.
NO_ARGUMENT_HOOKS = frozenset(
    {
        "depends",
        "depends_context",
        "constrains",
        "onchange",
        "ondelete",
    }
)


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
    method: str
    hook: str
    extra: str
    fatal: bool

    def __str__(self) -> str:
        verdict = "TypeError" if self.fatal else "masked"
        return (
            f"  {verdict:10}  {self.file}:{self.line}  @api.{self.hook} "
            f"{self.method}({self.extra})"
        )


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


def _hook_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    names = set()
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        name = getattr(target, "attr", getattr(target, "id", ""))
        if name in NO_ARGUMENT_HOOKS:
            names.add(name)
    return names


def _surplus(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[list[str], bool]:
    """Parameters the ORM cannot supply, and whether calling with none raises."""
    args = node.args
    positional = [a.arg for a in (*args.posonlyargs, *args.args)][1:]
    surplus = [*positional, *(a.arg for a in args.kwonlyargs)]
    if args.vararg:
        surplus.append(f"*{args.vararg.arg}")
    if args.kwarg:
        surplus.append(f"**{args.kwarg.arg}")
    # A default, or *args/**kwargs, makes the no-argument call succeed -- the
    # decorator is still on the wrong method, but nothing raises to say so.
    covered = len(args.defaults) + sum(d is not None for d in args.kw_defaults)
    masked = bool(args.vararg or args.kwarg) or covered >= len(positional) + len(
        args.kwonlyargs
    )
    return surplus, not masked


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
        try:
            tree = ast.parse(path.read_bytes())
        except SyntaxError:
            continue
        display = _sources.display(path, ROOT)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            hooks = _hook_names(node)
            if not hooks:
                continue
            surplus, fatal = _surplus(node)
            if not surplus:
                continue
            found.append(
                Offence(
                    display,
                    node.lineno,
                    node.name,
                    "/".join(sorted(hooks)),
                    ", ".join(surplus),
                    fatal,
                )
            )
    found.sort(key=lambda f: (f.file, f.line))
    return found


def main(argv: list[str] | None = None) -> int:
    return _count_gate.run(
        argv,
        script="py_hook_arity.py",
        gate="py_hook_arity",
        headline="ORM hooks the framework cannot call (ADR-0077, {where})",
        unit="hook(s)",
        default_addon=DEFAULT_ADDON,
        everything=ALL_ADDONS,
        siblings=SIBLING_SCOPES,
        governed=GOVERNED_ADDONS,
        addon_src=addon_src,
        measure=measure,
        root_name=ROOT.name,
        summary=lambda found: (
            f"  {sum(f.fatal for f in found)} raise TypeError when the ORM calls them; "
            f"{sum(not f.fatal for f in found)} are masked by a default"
        ),
    )


if __name__ == "__main__":
    sys.exit(main())

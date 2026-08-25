#!/usr/bin/env python3
"""Run test_lint's Python AST checkers over any roots, without odoo-bin.

WHY THIS EXISTS. The checkers live in an odoo *addon*, so the only way to run
them was to install `test_lint` into a database, and `lint_case.is_core_path`
scopes every gate to the checkout the framework is running from. The sibling
repositories are therefore checked by nothing at all. Measured 2026-08-25 with
this script, under exactly the corpus rules the gate applies:

    agromarin        1760 files    156 findings   (81 n-plus-one, 22 sql-injection, ...)
    enterprise       7786 files    731 findings   (423 n-plus-one, 275 noqa-rationale, ...)
    design-themes     129 files      2 findings
    ---------------------------------------------
                                    889, against 557 in the repository that is gated

WHAT THIS IS AND IS NOT. It is the capability: the same checkers, the same
suppression rules, the same corpus exclusions, pointable at any tree, so
`--count` can be ratcheted the way `naming_vocabulary.py` is. It is NOT coverage
yet -- nothing runs it in CI. Wiring it into the sibling repositories' own
"Architecture Boundaries (cross-repo)" workflows, which already check this fork
out beside themselves, is the step that turns a capability into a gate, and it
has to happen in those repositories. Until then this is a tool a developer runs,
and no baseline is committed for a scope nothing measures.

    python tooling/lint/py_lint.py ../agromarin --count
    python tooling/lint/py_lint.py ../agromarin --rule sql-injection
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
CHECKERS_DIR = REPO / "odoo" / "addons" / "test_lint" / "tests"

#: Mirrors `_py_scan._NOT_OURS`. Kept in step by
#: `tooling/lint/test_py_lint.py`, which reads both and compares.
NOT_OURS = (
    "/_vendor/",
    "/upgrades/",
    "/migrations/",
    "/node_modules/",
    "/__pycache__/",
)


def _load(name: str):
    """Import one checker module by path, as a member of a synthetic package.

    The modules use relative imports (`from ._suppression import ...`), so they
    need a package to be relative *to*; `_test_lint_checkers` is that package,
    rooted at the tests directory. Loading them this way rather than moving nine
    files into `tooling/` keeps the gate and this script running the same code,
    which is the only property that matters here.
    """
    package = "_test_lint_checkers"
    if package not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            package,
            CHECKERS_DIR / "__init__.py",
            submodule_search_locations=[str(CHECKERS_DIR)],
        )
        module = importlib.util.module_from_spec(spec)
        # A bare namespace: executing the real `__init__` would import every test
        # module, and those do need odoo.
        sys.modules[package] = module
    full = f"{package}.{name}"
    if full in sys.modules:
        return sys.modules[full]
    spec = importlib.util.spec_from_file_location(full, CHECKERS_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[full] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[full]
        raise
    return module


def _rules_module():
    for dependency in (
        "_suppression",
        "_checker_batch",
        "_checker_config_patch",
        "_checker_gettext",
        "_checker_noqa_rationale",
        "_checker_onchange",
        "_checker_orm_import",
        "_checker_sql",
        "_checker_unlink",
        "_checker_translated_unique",
    ):
        _load(dependency)
    return _load("_rules"), _load("_suppression"), _load("_checker_translated_unique")


def python_files(roots: list[str]) -> list[str]:
    out: list[str] = []
    for root in roots:
        for dirpath, dirnames, filenames in Path(root).walk():
            dirnames[:] = [
                d for d in dirnames if d not in ("__pycache__", "node_modules", ".git")
            ]
            out.extend(
                str(dirpath / filename)
                for filename in filenames
                if filename.endswith(".py")
                and not any(part in str(dirpath / filename) for part in NOT_OURS)
            )
    return sorted(out)


def in_an_addon(path: str) -> bool:
    """Is this file part of an addon, or part of the framework?

    `orm-import` -- the facade rule -- applies to addon code and not to the ORM
    itself, so getting this wrong makes the framework report 23 findings against
    the gate's 0. An addon is a directory with a `__manifest__.py`; everything
    above the nearest one is framework. In a sibling repository every file is in
    an addon, which is why this only shows up when the tool is pointed here.
    """
    for parent in Path(path).parents:
        if (parent / "__manifest__.py").is_file():
            return True
        if (parent / "odoo-bin").is_file():
            return False
    return False


def scan(roots: list[str]):
    import ast

    rules, suppression, translated = _rules_module()
    findings = []
    units = []
    for path in python_files(roots):
        try:
            raw = Path(path).read_bytes()
            text = raw.decode("utf-8", errors="replace")
            tree = ast.parse(raw, path)
            comments = suppression.comment_lines(text)
        except (OSError, SyntaxError, ValueError, suppression.Untokenisable) as exc:
            findings.append(
                ("unreadable-source", path, 1, f"{type(exc).__name__}: {exc}")
            )
            continue

        unit = rules.Unit(
            path,
            text,
            tree,
            rules.walk_with_parents(tree),
            in_an_addon(path),
            rules.is_test_path(path),
            comments,
        )
        suppresses = suppression.Suppressions(
            comments, rules.ALIASES, rules.UNSUPPRESSABLE
        )
        for checker in rules.CHECKERS:
            if not checker.applies_to(unit):
                continue
            try:
                violations = list(checker.run(unit))
            except RecursionError:
                continue
            for violation in violations:
                name = checker.rule or violation.rule
                if suppresses.suppresses(violation.lineno, name):
                    continue
                findings.append(
                    (name, path, violation.lineno, getattr(violation, "message", ""))
                )
        infos = translated.collect(tree)
        if infos:
            units.append((path, infos))

    findings.extend(
        (violation.rule, violation.path, violation.lineno, str(violation))
        for violation in translated.violations(units)
        if not rules.is_test_path(violation.path)
    )
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="py_lint.py", description=__doc__.split("\n")[0]
    )
    parser.add_argument("roots", nargs="+", help="directories to scan")
    parser.add_argument("--rule", help="only this rule")
    parser.add_argument(
        "--count", action="store_true", help="print counts, not findings"
    )
    args = parser.parse_args(argv)

    findings = scan(args.roots)
    if args.rule:
        findings = [f for f in findings if f[0] == args.rule]

    if args.count:
        by_rule = Counter(rule for rule, *_ in findings)
        for rule, n in sorted(by_rule.items(), key=lambda kv: (-kv[1], kv[0])):
            print(f"{n:6d}  {rule}")
        print(f"{len(findings):6d}  TOTAL")
    else:
        for rule, path, lineno, message in sorted(
            findings, key=lambda f: (f[1], f[2], f[0])
        ):
            print(f"{path}:{lineno} [{rule}] {message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

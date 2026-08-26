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

Each sibling repository runs `--check` from its own "Architecture Boundaries
(cross-repo)" workflow, which already checks this fork out beside itself. The
floors live here, in `tooling/ratchet/baselines/lint_<rule>_<scope>.json`,
because that is where the gate and every other floor live -- scoped by
provenance, so a run judges only its own repository's count.

    python tooling/lint/py_lint.py ../agromarin --count
    python tooling/lint/py_lint.py ../agromarin --rule sql-injection
    python tooling/lint/py_lint.py ../agromarin --count --rule sql-injection   # bare integer
    python tooling/lint/py_lint.py agromarin --check --scope agromarin

`--check` defaults to `--mode no-increase` for the same reason the other
cross-repo ratchets do: an exact floor across a repository boundary would make
every fix in a sibling red until a matching commit landed here to bank it.
Growth still fails. Lowering a sibling floor is done by hand from a workspace
that holds all four checkouts, which is what `naming` already asks for.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

HERE = Path(__file__).resolve().parent
REPO = find_odoo_root(Path(__file__).resolve(), tool="py_lint")
CHECKERS_DIR = REPO / "odoo" / "addons" / "test_lint" / "tests"

NOT_OURS = (
    "/_vendor/",
    "/upgrades/",
    "/migrations/",
    "/node_modules/",
    "/__pycache__/",
)


def _load(name: str):
    package = "_test_lint_checkers"
    if package not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            package,
            CHECKERS_DIR / "__init__.py",
            submodule_search_locations=[str(CHECKERS_DIR)],
        )
        module = importlib.util.module_from_spec(spec)
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
        spans = rules.statement_spans(unit.nodes)
        for checker in rules.CHECKERS:
            if not checker.applies_to(unit):
                continue
            try:
                violations = list(checker.run(unit))
            except RecursionError:
                continue
            for violation in violations:
                name = checker.rule or violation.rule
                if suppresses.suppresses(
                    violation.lineno,
                    name,
                    rules.directive_lines(spans, violation.lineno),
                ):
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


def _ratchet():
    name = "_py_lint_ratchet"
    if name in sys.modules:
        return sys.modules[name]
    path = REPO / "tooling" / "ratchet" / "ratchet.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[name]
        raise
    return module


def gate_name(rule: str, scope: str) -> str:
    return f"lint_{rule.replace('-', '_')}_{scope}"


def check(findings, scope: str, mode: str) -> int:
    ratchet = _ratchet()
    counts = Counter(rule for rule, *_ in findings)
    rules = sorted(set(counts) | _scoped_gates(ratchet, scope))
    worst = 0
    for rule in rules:
        gate = gate_name(rule, scope)
        baseline = ratchet.Baseline.load(gate)
        if baseline is None:
            baseline = ratchet.Baseline(count=0)
        verdict = ratchet.evaluate(gate, counts.get(rule, 0), baseline, mode)
        print(f"[{'OK' if verdict.ok else 'FAIL'}] {verdict.message}")
        if not verdict.ok:
            worst = 1
    if not rules:
        print(f"no findings and no baselines for scope {scope!r}")
    return worst


def _scoped_gates(ratchet, scope: str) -> set[str]:
    suffix = f"_{scope}.json"
    return {
        path.name[len("lint_") : -len(suffix)].replace("_", "-")
        for path in ratchet.BASELINES_DIR.glob(f"lint_*{suffix}")
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="py_lint.py", description=__doc__)
    parser.add_argument("roots", nargs="+", help="directories to scan")
    parser.add_argument("--rule", help="only this rule")
    parser.add_argument(
        "--count", action="store_true", help="print counts, not findings"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="hold every rule at its committed floor for --scope",
    )
    parser.add_argument("--scope", help="provenance tag for --check, e.g. agromarin")
    parser.add_argument(
        "--mode",
        choices=("exact", "no-increase"),
        default="no-increase",
        help="ratchet mode for --check (default: no-increase, see the module docstring)",
    )
    args = parser.parse_args(argv)

    if args.check and not args.scope:
        parser.error("--check needs --scope")

    findings = scan(args.roots)
    if args.rule:
        findings = [f for f in findings if f[0] == args.rule]

    if args.check:
        return check(findings, args.scope, args.mode)

    if args.count and args.rule:
        print(len(findings))
    elif args.count:
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

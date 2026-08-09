#!/usr/bin/env python3
"""Default-deny mypy gate, one lock per core package.

The Python counterpart of ``scope_gate.py``, whose argument holds here word for
word: an allowlist enumerates what is *enforced*, so a new or renamed file is
unenforced by default and silently. The Python side never had an allowlist to
invert — it has something weaker, a single count
(``tooling/ratchet/baselines/mypy.json``, floor 1286). Measured on the run that
produced that floor (mypy 2.3.0, the pin in ``requirements-dev.txt``):

    checked 469 source files, 1286 errors in 189 files
    -> 280 files (59%) are ALREADY clean, and none of them was locked

Any of those 280 may regress by *N* errors and CI stays green so long as some
unrelated file improves by *N*. Demonstrated, not assumed: moving one error off
``odoo/modules/loading.py`` and onto ``odoo/orm/__init__.py`` — clean, and the
package's own entry point — leaves the total at exactly 1286, and
``tooling/ratchet`` reports ``No drift``. ``test_py_scope_gate.py`` pins that
scenario, since it is the whole reason this file exists.

That is the fungible-slack failure ``doc/architecture/gates.md`` already
diagnosed for ``ruff_docstring``: "an exact-match ratchet over one integer
cannot distinguish 'someone added a docstring' from 'someone introduced a real
lint defect'". Splitting the floor fixed the diagnosis for ruff. Inverting the
model is what fixes it here, and the JS side has the inversion already.

**Two locks, because membership alone is not enough at 1286.** ``strict-web``
carries the same pair for the same reason:

  * ``exceptions/mypy/<pkg>.txt`` — the files not yet clean. Shrink-only.
  * ``budgets/mypy-<pkg>.json``  — a per-file ceiling for each excepted file, so
    an excepted file cannot get *worse* either. Without it the 189 files holding
    all 1286 errors would be a fungible pool again, just a smaller one.

Verdicts mirror the JS gate, and each is a failure:

    regressed     in scope, erroring, not excepted
    over-budget   excepted, but above its recorded ceiling
    cleared       excepted and now clean — remove it from the list
    stale         an excepted path no longer exists (the rename hole)
    out-of-scope  an excepted path is outside the package whose list holds it
    unchecked     in scope, but mypy never looked at it

``--verbose`` is required on the mypy run for the same reason ``--listFiles``
is on the tsc one: without the list of files actually checked, a file mypy
skipped is indistinguishable from a file mypy found clean, and the gate would
count it as locked while nothing enforces it.

Use::

    mypy --no-incremental --config-file mypy.ini \\
        -p odoo.orm -p odoo.db -p odoo.libs -p odoo.http -p odoo.service \\
        -p odoo.modules --verbose > /tmp/mypy.log 2>&1 || true
    python tooling/typecheck/py_scope_gate.py --log /tmp/mypy.log            # report
    python tooling/typecheck/py_scope_gate.py --log /tmp/mypy.log --check    # CI
    python tooling/typecheck/py_scope_gate.py --log /tmp/mypy.log --update   # re-seed
    python tooling/typecheck/py_scope_gate.py --log /tmp/mypy.log --report   # what next

Self-test: ``python tooling/typecheck/test_py_scope_gate.py`` — stdlib
``unittest``, no Odoo import, no database.
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from _repo_root import find_odoo_root  # noqa: E402

ROOT = find_odoo_root(Path(__file__).resolve(), tool="py_scope_gate")
EXCEPTIONS_DIR = HERE / "exceptions" / "mypy"
BUDGETS_DIR = HERE / "budgets"

# The packages mypy.ini checks, mirroring the -p flags in
# .github/workflows/py_typecheck.yml. Committed here rather than passed on the
# command line so CI and a local run cannot silently disagree about what is
# enforced — the same reason SCOPED_MODULES lives in scope_gate.py.
#
# Adding one is a two-step change: append it here, then regenerate its lists
# with --update in the same commit. Coverage as seeded (2026-08-09):
#
#     package    files  locked        note
#     libs         154  113 (73%)     lockable now; 41 exceptions
#     db            40   29 (72%)     lockable now; 11 exceptions
#     modules        9    5 (56%)
#     orm          181   89 (49%)     765 of the 1286 errors
#     http          39   18 (46%)
#     service       25    5 (20%)     the debt; 95 errors over 20 files
SCOPED_PACKAGES = ("orm", "db", "libs", "http", "service", "modules")

# mypy reports paths repo-relative already, but a run given an absolute config
# path emits absolute ones. Both are normalised before anything compares them.
ERROR_LINE_RE = re.compile(
    r"^(?P<path>[^\s:][^:]*\.py):(?P<line>\d+):(?P<col>\d+): error: "
    r"(?P<msg>.*?)(?P<code>\[[a-z-]+\])?$"
)

# ``LOG:  Parsing /abs/path.py (odoo.orm.x)`` — the trailing module name is why
# this is not anchored at end-of-line.
PARSED_LINE_RE = re.compile(r"^LOG: +Parsing (?P<path>\S+\.py)")

# Exit codes (stable, for CI to branch on) — same contract as scope_gate.py.
EXIT_OK = 0
EXIT_DRIFT = 1
EXIT_USAGE = 2

# Per-code cleanup ease in [0, 1], higher = more likely a local fix. Same scale
# and direction as scope_gate.py's, so the two --report outputs read alike. Used
# only to rank; it steers attention and never affects the verdict.
CODE_EASE = {
    "[var-annotated]": 1.0,  # needs an annotation, no logic to reason about
    "[no-untyped-def]": 1.0,
    "[no-any-return]": 0.8,
    "[redundant-cast]": 0.9,
    "[union-attr]": 0.6,  # usually one missing None guard
    "[index]": 0.5,
    "[assignment]": 0.5,
    "[arg-type]": 0.4,
    "[operator]": 0.3,
    "[attr-defined]": 0.3,  # often a real modelling gap, not a local fix
    "[misc]": 0.2,
}
DEFAULT_EASE = 0.5


def normalise(path: str) -> str:
    """Absolute or repo-relative path -> repo-relative POSIX form."""
    candidate = Path(path)
    if candidate.is_absolute():
        try:
            candidate = candidate.relative_to(ROOT)
        except ValueError:
            return candidate.as_posix()
    return candidate.as_posix()


def package_of(path: str) -> str | None:
    """The gated package a repo-relative path belongs to, or None if unscoped."""
    parts = normalise(path).split("/")
    if len(parts) >= 3 and parts[0] == "odoo" and parts[1] in SCOPED_PACKAGES:
        return parts[1]
    return None


def in_scope(path: str) -> bool:
    return package_of(path) is not None


def parse_log(text: str) -> tuple[dict[str, dict[str, int]], set[str]]:
    """``(errors_by_path_by_code, paths_mypy_actually_checked)``.

    Both restricted to the gated packages: a followed import outside them is
    reported by neither, which is what ``follow_imports = silent`` intends.
    """
    errors: dict[str, dict[str, int]] = collections.defaultdict(collections.Counter)
    checked: set[str] = set()
    for line in text.splitlines():
        if match := PARSED_LINE_RE.match(line):
            path = normalise(match["path"])
            if in_scope(path):
                checked.add(path)
        elif match := ERROR_LINE_RE.match(line):
            path = normalise(match["path"])
            if in_scope(path):
                errors[path][match["code"] or "[none]"] += 1
    return {p: dict(c) for p, c in errors.items()}, checked


def total(codes: dict[str, int]) -> int:
    return sum(codes.values())


def package_files(package: str) -> set[str]:
    """Every ``.py`` under a gated package, repo-relative."""
    root = ROOT / "odoo" / package
    return {
        path.relative_to(ROOT).as_posix()
        for path in root.rglob("*.py")
        if "__pycache__" not in path.parts
    }


def exceptions_path(package: str) -> Path:
    return EXCEPTIONS_DIR / f"{package}.txt"


def budgets_path(package: str) -> Path:
    return BUDGETS_DIR / f"mypy-{package}.json"


def read_exceptions(package: str) -> list[str]:
    path = exceptions_path(package)
    if not path.is_file():
        return []
    return [
        line.strip()
        for line in path.read_text(encoding="utf8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def read_budgets(package: str) -> dict[str, int]:
    path = budgets_path(package)
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf8"))["budgets"]


@dataclass
class PackageVerdict:
    package: str
    locked: int = 0
    excepted: int = 0
    regressed: list[str] = field(default_factory=list)
    over_budget: list[tuple[str, int, int]] = field(default_factory=list)
    cleared: list[str] = field(default_factory=list)
    stale: list[str] = field(default_factory=list)
    out_of_scope: list[str] = field(default_factory=list)
    unchecked: list[str] = field(default_factory=list)

    @property
    def failures(self) -> int:
        return (
            len(self.regressed)
            + len(self.over_budget)
            + len(self.cleared)
            + len(self.stale)
            + len(self.out_of_scope)
            + len(self.unchecked)
        )

    @property
    def coverage(self) -> float:
        gated = self.locked + self.excepted
        return self.locked / gated if gated else 1.0


def evaluate_package(
    package: str,
    errors: dict[str, dict[str, int]],
    checked: set[str],
    exempt: list[str] | None = None,
    budgets: dict[str, int] | None = None,
    on_disk: set[str] | None = None,
) -> PackageVerdict:
    """The verdict for one package.

    Every input is a parameter rather than a read of the committed state so the
    self-test can judge a synthetic tree without this checkout's debt leaking
    into it — the reason ``js_layer_cohesion.find_drift`` takes ``known``.
    """
    verdict = PackageVerdict(package)
    disk = package_files(package) if on_disk is None else on_disk
    listed = read_exceptions(package) if exempt is None else exempt
    ceilings = read_budgets(package) if budgets is None else budgets
    exempted = set(listed)

    verdict.stale = sorted(e for e in exempted if e not in disk)
    verdict.out_of_scope = sorted(e for e in exempted if package_of(e) != package)
    # A file mypy never checked is silent, and silence is not evidence of
    # cleanliness — counting it as locked is exactly the hole this gate closes.
    verdict.unchecked = sorted(disk - checked - exempted)

    gated = disk & checked
    errored = {f for f in gated if total(errors.get(f, {})) > 0}
    verdict.regressed = sorted(errored - exempted)
    verdict.cleared = sorted(
        e for e in exempted if e in gated and total(errors.get(e, {})) == 0
    )
    verdict.over_budget = sorted(
        (e, total(errors[e]), ceilings[e])
        for e in exempted
        if e in errors and e in ceilings and total(errors[e]) > ceilings[e]
    )
    verdict.excepted = len(exempted & disk)
    verdict.locked = len(gated - exempted)
    return verdict


def write_state(errors: dict[str, dict[str, int]], checked: set[str]) -> list[Path]:
    """Regenerate every exception list and budget file. Returns what was written."""
    written = []
    EXCEPTIONS_DIR.mkdir(parents=True, exist_ok=True)
    BUDGETS_DIR.mkdir(parents=True, exist_ok=True)
    for package in SCOPED_PACKAGES:
        failing = sorted(
            f for f in package_files(package) & checked if total(errors.get(f, {})) > 0
        )
        listing = exceptions_path(package)
        listing.write_text(
            f"# mypy / {package}: files NOT yet clean under mypy.ini — the\n"
            f"# EXCEPTIONS to a default-deny gate, so this list may only shrink.\n"
            f"# Everything else under odoo/{package}/ is locked at zero, including\n"
            f"# files added after this list was written. Per-file ceilings for the\n"
            f"# entries below are in budgets/mypy-{package}.json.\n#\n"
            + "".join(f"{f}\n" for f in failing),
            encoding="utf8",
        )
        budgets = budgets_path(package)
        budgets.write_text(
            json.dumps(
                {
                    "gate": "mypy",
                    "package": package,
                    "total": sum(total(errors[f]) for f in failing),
                    "note": (
                        "Per-file ceilings for the files mypy excepts; membership "
                        f"still comes from exceptions/mypy/{package}.txt. Harvested "
                        "with the mypy version pinned in requirements-dev.txt — a "
                        "different version reports different counts."
                    ),
                    "budgets": {f: total(errors[f]) for f in failing},
                },
                indent=2,
            )
            + "\n",
            encoding="utf8",
        )
        written += [listing, budgets]
    return written


def rank(errors: dict[str, dict[str, int]]) -> list[tuple[float, int, str]]:
    """Excepted files by payoff — count x mean ease, best first."""
    rows = []
    for package in SCOPED_PACKAGES:
        for path in read_exceptions(package):
            codes = errors.get(path, {})
            count = total(codes)
            if not count:
                continue
            ease = sum(CODE_EASE.get(c, DEFAULT_EASE) * n for c, n in codes.items())
            rows.append((ease, count, path))
    return sorted(rows, reverse=True)


def report(verdicts: list[PackageVerdict], stream=sys.stdout) -> None:
    print(
        f"\n  {'package':10s} {'locked':>7} {'excepted':>9} {'coverage':>9}",
        file=stream,
    )
    for verdict in verdicts:
        flag = "" if not verdict.failures else f"   {verdict.failures} FAIL"
        print(
            f"  {verdict.package:10s} {verdict.locked:7d} {verdict.excepted:9d}"
            f" {verdict.coverage:8.0%}{flag}",
            file=stream,
        )
    locked = sum(v.locked for v in verdicts)
    excepted = sum(v.excepted for v in verdicts)
    gated = locked + excepted
    print(
        f"  {'TOTAL':10s} {locked:7d} {excepted:9d}"
        f" {(locked / gated if gated else 1):8.0%}",
        file=stream,
    )
    for verdict in verdicts:
        for kind in ("regressed", "cleared", "stale", "out_of_scope", "unchecked"):
            items = getattr(verdict, kind)
            if not items:
                continue
            print(
                f"\n  {kind.replace('_', '-')} ({verdict.package}): {len(items)}",
                file=stream,
            )
            for item in items[:10]:
                print(f"    {item}", file=stream)
            if len(items) > 10:
                print(f"    … {len(items) - 10} more", file=stream)
        for path, got, ceiling in verdict.over_budget:
            print(
                f"\n  over-budget ({verdict.package}): {path} — {got} > {ceiling}",
                file=stream,
            )


def markdown(verdicts: list[PackageVerdict], stream=sys.stdout) -> None:
    """The GitHub step-summary table.

    Emitted by the gate rather than by a heredoc in the workflow: a Python
    block scalar nested inside a YAML one has to be indented to stay inside it,
    and a single wrong column silently breaks the workflow file instead of the
    step. Here it is also covered by the self-test.
    """
    print("| Package | Locked | Excepted | Coverage | Failures |", file=stream)
    print("|---------|-------:|---------:|---------:|---------:|", file=stream)
    for verdict in verdicts:
        print(
            f"| `{verdict.package}` | {verdict.locked} | {verdict.excepted} "
            f"| {verdict.coverage:.0%} | {verdict.failures or ''} |",
            file=stream,
        )
    locked = sum(v.locked for v in verdicts)
    excepted = sum(v.excepted for v in verdicts)
    failures = sum(v.failures for v in verdicts)
    gated = locked + excepted
    # Built before interpolation: `**{failures or ''}**` renders as a literal
    # `****` on a green run, which is broken markdown rather than an empty cell.
    failed_cell = f"**{failures}**" if failures else "—"
    print(
        f"| **total** | **{locked}** | **{excepted}** "
        f"| **{(locked / gated if gated else 1):.0%}** | {failed_cell} |",
        file=stream,
    )
    if failures:
        print(
            "\n> :x: A locked file regressed, or a list needs updating — see the "
            "`Enforce per-file locks` step.",
            file=stream,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", required=True, type=Path, help="mypy --verbose output")
    parser.add_argument("--check", action="store_true", help="exit 1 on any failure")
    parser.add_argument("--update", action="store_true", help="regenerate the lists")
    parser.add_argument("--report", action="store_true", help="rank what to fix next")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--markdown", action="store_true", help="step-summary table (never exits 1)"
    )
    args = parser.parse_args(argv)

    if not args.log.is_file():
        print(f"py_scope_gate: no such log: {args.log}", file=sys.stderr)
        return EXIT_USAGE

    errors, checked = parse_log(args.log.read_text(encoding="utf8", errors="replace"))
    if not checked:
        # A log with no Parsing lines was produced without --verbose. Every file
        # would read as `unchecked` and the run would fail for the wrong reason.
        print(
            "py_scope_gate: the log names no checked files — rerun mypy with "
            "--verbose (see this module's docstring)",
            file=sys.stderr,
        )
        return EXIT_USAGE

    if args.update:
        for path in write_state(errors, checked):
            print(f"wrote {path.relative_to(ROOT)}")

    verdicts = [evaluate_package(p, errors, checked) for p in SCOPED_PACKAGES]

    if args.report:
        print(f"\n  {'ease':>6} {'errs':>5}  file   (best payoff first)")
        for ease, count, path in rank(errors)[:25]:
            print(f"  {ease:6.1f} {count:5d}  {path}")
        return EXIT_OK

    if args.markdown:
        markdown(verdicts)
        return EXIT_OK

    if args.json:
        print(
            json.dumps(
                {
                    v.package: {
                        "locked": v.locked,
                        "excepted": v.excepted,
                        "regressed": v.regressed,
                        "over_budget": v.over_budget,
                        "cleared": v.cleared,
                        "stale": v.stale,
                        "out_of_scope": v.out_of_scope,
                        "unchecked": v.unchecked,
                    }
                    for v in verdicts
                },
                indent=2,
            )
        )
    else:
        report(verdicts)

    failures = sum(v.failures for v in verdicts)
    return EXIT_DRIFT if (args.check and failures) else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())

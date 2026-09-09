"""Re-measure every ratchet floor that can be re-measured cheaply, and name the rest.

`ratchet.py --list` answers a question about a floor's *provenance* -- is
`measured_at` an ancestor of HEAD -- and never re-runs the gate. So a floor whose
stamp resolves perfectly can be wrong about the tree in either direction for as
long as nobody runs that particular gate, and `--list` keeps reporting it clean.
CLAUDE.md §4 states that as a rule; on 2026-09-09 it acquired a number. Seventeen
of the cheap architecture floors were measured against their banked counts and
**seven** disagreed, every one above its floor and every one with a reachable
stamp. That is not a diligence problem. It is that nothing in the repository
turned a floor name into the command that measures it.

`RUNNERS` below is that missing lookup, and it is the whole content of this
module. The names are not derivable -- `computectx` is `compute_context_deps.py`,
`translations` is `translation_catalog.py`, `pyclasslen` is `py_class_length.py`
-- so a survey that anybody could have run at any time was one nobody could
start.

**A floor this tool does not measure is reported, never omitted.** That is the
single rule the design turns on, and it is the trap the original problem was:
a survey whose output looks complete while silently covering half the floors
recreates the failure it exists to detect, one level up. `UNCOVERED` carries a
reason per floor and the summary counts it separately from the passes; a green
run means "the floors named VERIFIED agree with the tree", never "the floors
agree with the tree".

Deliberately not a gate. It fails nothing, has no baseline of its own and binds
no ADR: what it reports is *other* gates' verdicts, and a wrapper that could fail
on its own would be an eighty-fifth floor to keep honest. Run it after a sweep,
and read the drift lines.

    python tooling/ratchet/survey.py                 # architecture floors
    python tooling/ratchet/survey.py --siblings      # + the sibling lint scopes
    python tooling/ratchet/survey.py --json

**A delta is where the work starts; the set diff is the finding.** This module
reports counts, and a count cannot see a relocation: `computectx` moved +4 on a
raw reading, and the set diff was five new offenders, one relocated between
addons and cancelling itself, and one genuinely fixed. Nor can a count separate
*the tree moved* from *the scan moved*, which is §4's middle failure mode and the
one no amount of re-running detects — for that, run the CURRENT gate against the
OLD tree at the floor's own `measured_at`: equal scans over two trees isolates
the tree, and it is the only comparison that can be made after the fact. Take a
drift line as a question, answer it with `--json` on both sides, and put the
decomposition in the banking note.

**Measure in a detached worktree at a commit, never in a shared checkout.** The
survey that produced the seven was first run in a tree six sessions were dirty
in, and returned the identical seven -- correct by luck, which is the worst
outcome available, because a wrong method that returns the right answer teaches
you to keep using it. A count taken from a dirty tree cannot separate drift from
somebody's unlanded work.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ratchet

ROOT = ratchet.BASELINES_DIR.parents[2]
ARCH = ROOT / "tooling" / "architecture"

# floor -> (script under tooling/architecture, extra argv before --count).
# Every entry here was verified by running it, not by reading the name.
RUNNERS: dict[str, tuple[str, list[str]]] = {
    "bridge_budget": ("bridge_budget.py", []),
    "computectx": ("compute_context_deps.py", []),
    "config_in_addons": ("config_in_addons.py", []),
    "fieldhooks": ("field_hook_naming.py", []),
    "hookpurity": ("field_hook_purity.py", []),
    "jsforcedrender": ("js_forced_render.py", []),
    "jsprivate": ("js_private_access.py", []),
    "jstscheck": ("js_ts_check.py", []),
    "jsvacuous": ("js_vacuous_assertions.py", []),
    "naming": ("naming_vocabulary.py", []),
    "orphandepends": ("orphan_depends.py", []),
    "pyclasslen": ("py_class_length.py", []),
    "pyfunclen": ("py_function_length.py", ["--addon", "core"]),
    "py_x2many_count": ("py_x2many_count.py", []),
    "translations": ("translation_catalog.py", []),
    "werkzeug_in_addons": ("werkzeug_in_addons.py", []),
    "jsfunclen": ("js_function_length.py", ["--addon", "web"]),
    "jsfunclen_account": ("js_function_length.py", ["--addon", "account"]),
    "jsfunclen_mail": ("js_function_length.py", ["--addon", "mail"]),
    "jsfunclen_survey": ("js_function_length.py", ["--addon", "survey"]),
    "jsclasslen": ("js_class_length.py", []),
    "jsduplication": ("js_duplication.py", []),
    "jsprivate_crosstree": ("js_private_access.py", ["--count-cross-tree"]),
    "jsserviceshape": ("js_service_shape.py", ["--addon", "web"]),
    "jsserviceshape_mail": ("js_service_shape.py", ["--addon", "mail"]),
    "jsunreached": ("js_unreached_assertions.py", ["--addon", "web"]),
    "naming_agromarin": ("naming_vocabulary.py", ["--roots", "../agromarin"]),
    "naming_enterprise": ("naming_vocabulary.py", ["--roots", "../enterprise"]),
    "orderlineqty": ("order_line_qty.py", []),
    "orderlineqty_enterprise": ("order_line_qty.py", ["--roots", "../enterprise"]),
    "py_shadowed_member_addons": ("py_shadowed_member.py", ["--addon", "addons"]),
    "py_x2many_count_account": ("py_x2many_count.py", ["--addon", "account"]),
    "py_x2many_count_addons": ("py_x2many_count.py", ["--addon", "addons"]),
    "pyclasslen_addons": ("py_class_length.py", ["--addon", "addons"]),
    "pyfunclen_addons": ("py_function_length.py", ["--addon", "addons"]),
    "pyfunclen_crm": ("py_function_length.py", ["--addon", "crm"]),
    "pyfunclen_mail": ("py_function_length.py", ["--addon", "mail"]),
    "pyfunclen_survey": ("py_function_length.py", ["--addon", "survey"]),
    "pyfunclen_tooling": ("py_function_length.py", ["--addon", "tooling"]),
    "unresolved_calls": ("py_unresolved_calls.py", []),
    "unresolved_calls_agromarin": (
        "py_unresolved_calls.py",
        ["--roots", "../agromarin"],
    ),
    "unresolved_calls_enterprise": (
        "py_unresolved_calls.py",
        ["--roots", "../enterprise"],
    ),
    "py_x2many_count_agromarin": ("py_x2many_count.py", ["--addon", "agromarin"]),
    "py_x2many_count_enterprise": ("py_x2many_count.py", ["--addon", "enterprise"]),
}

# Why a floor is not in RUNNERS. A floor missing from BOTH mappings is a bug in
# this file, and `--json` reports it as `unmapped` so it cannot pass unnoticed.
UNCOVERED: dict[str, str] = {
    "mypy": "§9.3: measured with mypy and NOTHING else installed, so this venv's "
    "real stubs for lxml/psycopg/dateutil give a different number",
    "mypy_tools": "same clean-env requirement as mypy, over odoo.tools",
    "tsc": "needs node and a full tsc program over tsconfig.json",
    "tsc_serviceworker": "needs node, and one tsc program per deployed route "
    "because lib.dom and lib.webworker cannot share one",
    "prettier_scss": "needs npx prettier, which is not on PATH (§5)",
    "prettier_dts": "needs npx prettier, same",
    "ruff": "a hard zero over the core package; run ruff check odoo/ directly",
    "c901": "a ruff --select C901 run, not an architecture script",
    "c901_addons": "the same ruff --select over addons/, not a script here",
    "service_types_untyped": "lives in tooling/typecheck with its own runner",
}

SIBLING_SCOPES = (("agromarin", "agromarin"), ("enterprise", "enterprise"))

# §9.2: `--mode` is a CLI flag and not a field in the JSON, so the invocation
# decides and a survey has to know the same rule the invocation uses. Every
# cross-repo scope is measured `--mode no-increase`; on the odoo side
# `pyfunclen_addons` is the only one, because the bundled tree moves in both
# directions constantly. Everything else is `exact`, which fails on a DECREASE
# too -- an unbanked improvement is a floor nobody has locked in.
#
# Getting this wrong is not cosmetic: comparing counts for equality reports a
# no-increase floor that has improved by 384 as drift, and an instrument that
# cries wolf is one people stop running -- which is the failure this module
# exists to prevent, reintroduced by the module itself.
NO_INCREASE_SUFFIXES = ("_agromarin", "_enterprise", "_design-themes")
NO_INCREASE_GATES = frozenset({"pyfunclen_addons"})


def mode_for(gate: str) -> str:
    if gate in NO_INCREASE_GATES or gate.endswith(NO_INCREASE_SUFFIXES):
        return "no-increase"
    return "exact"


# The single most dangerous property of this module is that it measures WHEREVER
# IT IS RUN, and the sibling mappings make that invisible: `--roots ../enterprise`
# reads like it names a clean checkout and silently names the live one. Three
# sessions produced retracted numbers this way in one afternoon -- a 41-floor run
# against three dirty repos, a `computectx` post-fix count, and a scope probe --
# and in every case the output looked exactly like a clean reading. So the tree's
# provenance is reported ABOVE the table, never inferred, and never omitted.
def dirty_trees() -> dict[str, int]:
    """Repos this survey will scan that have uncommitted changes, and how many."""
    found: dict[str, int] = {}
    for label, path in (
        ("odoo", ROOT),
        *((r, ROOT.parent / r) for r, _ in SIBLING_SCOPES),
    ):
        if not (path / ".git").exists():
            continue
        out = subprocess.run(
            ["git", "-C", str(path), "status", "--porcelain", "--untracked-files=all"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if out.returncode == 0 and (
            n := len([x for x in out.stdout.splitlines() if x.strip()])
        ):
            found[label] = n
    return found


def _measure(script: str, args: list[str], timeout: int) -> int | None:
    try:
        out = subprocess.run(
            [sys.executable, str(ARCH / script), *args, "--count"],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=ROOT,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None
    tail = out.stdout.strip().splitlines()
    if not tail:
        return None
    try:
        return int(tail[-1].strip())
    except ValueError:
        return None


def survey(timeout: int = 420) -> list[dict]:
    rows: list[dict] = []
    for path in sorted(ratchet.BASELINES_DIR.glob("*.json")):
        gate = path.stem
        banked = json.loads(path.read_text(encoding="utf-8")).get("count")
        if gate in RUNNERS:
            script, args = RUNNERS[gate]
            got = _measure(script, args, timeout)
            if got is None:
                rows.append(
                    {
                        "gate": gate,
                        "banked": banked,
                        "measured": None,
                        "state": "unmeasurable",
                        "why": "runner produced no count -- the mapping is wrong",
                    }
                )
                continue
            # Ask the ratchet for the verdict rather than comparing counts here.
            # Reimplementing it is how a survey and the gate it surveys come to
            # disagree, which is the one thing this module must never do.
            mode = mode_for(gate)
            verdict = ratchet.evaluate(gate, got, ratchet.Baseline(count=banked), mode)
            if verdict.ok and got != banked:
                state = "unbanked-improvement"
            elif verdict.ok:
                state = "ok"
            else:
                state = "DRIFT"
            rows.append(
                {
                    "gate": gate,
                    "banked": banked,
                    "measured": got,
                    "state": state,
                    "mode": mode,
                }
            )
        elif gate in UNCOVERED:
            rows.append(
                {
                    "gate": gate,
                    "banked": banked,
                    "measured": None,
                    "state": "uncovered",
                    "why": UNCOVERED[gate],
                }
            )
        elif gate.startswith(("lint_", "bundle_")):
            rows.append(
                {
                    "gate": gate,
                    "banked": banked,
                    "measured": None,
                    "state": "uncovered",
                    "why": "lint family: sibling scopes via --siblings; the "
                    "odoo scope needs -i test_lint",
                }
            )
        else:
            rows.append(
                {
                    "gate": gate,
                    "banked": banked,
                    "measured": None,
                    "state": "unmapped",
                    "why": "no runner recorded -- add one to RUNNERS or UNCOVERED",
                }
            )
    return rows


def siblings(timeout: int = 420) -> int:
    worst = 0
    for repo, scope in SIBLING_SCOPES:
        target = ROOT.parent / repo
        if not target.is_dir():
            print(f"  {scope}: {target} not checked out, skipped")
            continue
        out = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tooling" / "lint" / "py_lint.py"),
                str(target),
                "--check",
                "--scope",
                scope,
                "--mode",
                "exact",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=ROOT,
            check=False,
        )
        for line in out.stdout.splitlines():
            if line.startswith("[FAIL]") or "No drift" not in line:
                print(f"  {line}")
                worst = 1
    return worst


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--siblings",
        action="store_true",
        help="also hold every sibling-repo lint floor at its floor",
    )
    parser.add_argument("--timeout", type=int, default=420)
    args = parser.parse_args(argv)

    rows = survey(args.timeout)
    if args.json:
        print(json.dumps(rows, indent=2))
        return 1 if any(r["state"] == "DRIFT" for r in rows) else 0

    drift = [r for r in rows if r["state"] == "DRIFT"]
    gain = [r for r in rows if r["state"] == "unbanked-improvement"]
    ok = [r for r in rows if r["state"] == "ok"]
    other = [r for r in rows if r["state"] in ("unmeasurable", "unmapped")]
    uncovered = [r for r in rows if r["state"] == "uncovered"]

    dirty = dirty_trees()
    print("Ratchet floors re-measured against the tree")
    print("=" * 72)
    if dirty:
        where = ", ".join(f"{r} {n} file(s)" for r, n in sorted(dirty.items()))
        print(f"  !! MEASURED AGAINST A DIRTY TREE: {where}")
        print("  !! These numbers describe nobody's commit. A count taken here")
        print("  !! cannot separate drift from another session's unlanded work,")
        print("  !! and must not be banked. Re-run from detached worktrees:")
        print("  !!   git -C <repo> worktree add --detach <ws>/<repo> HEAD")
        print("  !! laid out as a workspace, so the sibling paths resolve clean.")
        print("=" * 72)
    else:
        print("  every scanned tree is clean at its HEAD")
    for r in drift:
        delta = r["measured"] - r["banked"]
        print(
            f"  DRIFT  {r['gate']:26} banked {r['banked']:<8} measured "
            f"{r['measured']:<8} {delta:+d}"
        )
    for r in gain:
        delta = r["measured"] - r["banked"]
        print(
            f"  GAIN   {r['gate']:26} banked {r['banked']:<8} measured "
            f"{r['measured']:<8} {delta:+d}  (no-increase; bank it)"
        )
    for r in other:
        print(f"  {r['state'].upper():13}{r['gate']:26} {r.get('why', '')}")
    print("-" * 72)
    print(
        f"  {len(ok)} verified at their floor, {len(drift)} drifted, "
        f"{len(gain)} improved-unbanked, {len(other)} unmeasured, "
        f"{len(uncovered)} out of scope"
    )
    print(
        "\n  NOT COVERED is not VERIFIED -- see UNCOVERED in this module for why "
        "each\n  is out of scope, and §9 for the command that does measure it."
    )

    if args.siblings:
        print("\nSibling lint scopes (exact mode)")
        print("=" * 72)
        siblings(args.timeout)
    return 1 if drift else 0


if __name__ == "__main__":
    raise SystemExit(main())

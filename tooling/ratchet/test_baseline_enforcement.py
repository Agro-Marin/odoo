"""Every floor is run by a lane, and every lane names a floor that exists.

`ratchet.py` will happily create a baseline for any string handed to `--update`,
because `Baseline.save` writes whatever `baseline_path` names. A gate invoked as
`ratchet.py naming_vocabluary --count 143 --update` therefore lands a NEW floor
that nothing ever measures against, while the real one goes on drifting — and
`--list` shows both, side by side, indistinguishable.

That is the same fault every gate here is written to refuse. `py_x2many_count`
turns away an unknown `--addon` with "a floor over an unscanned tree checks
nothing while looking like it does"; `test_gate_adr_coverage` refuses a gate that
cites no record; `test_architecture_doc` fails when the directory and its index
disagree IN EITHER DIRECTION. The floors themselves had no such check: the
baselines directory and the workflows that read it were free to drift apart.

Both directions are asserted, for the same reason those do:

* a baseline nothing reads is debt nobody is paying down, and reads as
  governed;
* a WORKFLOW invocation naming no baseline is a lane that exits 2 on `error: no
  baseline for ...` the first time it runs — or, worse, one whose typo was
  already absorbed by an `--update`.

The second direction is deliberately not applied to the Python consumer:
`baseline_floor` returns 0 for a gate with no baseline, on the argument that a
gate carrying no debt needs no file. Both consumers keep a floor alive; only one
of them breaks when the file is missing.

A floor has TWO kinds of consumer and both count. Most are read by a workflow
step, `ratchet.py <gate> --count <n>`. The `test_lint` gates are read from
Python instead — `LintCase.assert_ratchet(findings, "<gate>", …)` loads the same
baseline through `Baseline.load` — because they measure an installed registry
and so cannot be a shell step. Judging only the first kind would report every
one of those as an unrun floor, which is a false alarm of exactly the shape this
file exists to stop.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

HERE = Path(__file__).resolve().parent
# Located by the `odoo-bin` marker rather than by counting `parents[]`: the count
# is silently wrong one directory either way, and a WORKFLOWS path that resolves
# to nothing makes every assertion below pass by finding nothing.
ROOT = find_odoo_root(Path(__file__).resolve(), tool="test_baseline_enforcement")
BASELINES_DIR = HERE / "baselines"
WORKFLOWS = ROOT / ".github" / "workflows"

#: `ratchet.py <gate> [--mode M] --count`, after physical line continuations are
#: folded away. The workflows wrap almost every invocation and the gate name is
#: regularly the first token of the continuation line, so matching per-line finds
#: nothing. The trailing `--count` is what separates an invocation from prose:
#: without it the header comments contribute `and`, `has` and `python` as gates.
_INVOCATION = re.compile(
    r"ratchet\.py\s+([a-z0-9_]+)(?:\s+--mode\s+\S+)?\s+--count\b"
)
_CONTINUATION = re.compile(r"\\\s*\n\s*")

#: A whole-line comment, in YAML or in a `run:` block's shell. Stripped BEFORE
#: continuations are folded, because four steps document the `--update` recipe
#: as a commented `ratchet.py <gate> --count "$N" --update` and those lines
#: otherwise register as enforcement: `eslint`, `mypy`, `ruff` and `tsc` all
#: read as run-by-a-lane from the comment alone, so deleting their real steps
#: would not fail this. A gate is enforced by a step, never by a sentence.
_COMMENT_LINE = re.compile(r"^[ \t]*#.*$", re.MULTILINE)

#: The Python-side consumer, anchored so the discovery below cannot go vacuous.
#: Not used to FIND the gate names: `test_xml_records.py` reaches the floor
#: through a local `_assert_clean(findings, "<gate>", …)` wrapper, and a
#: call-shape regex reported every gate behind such a wrapper as unreferenced.
#: Shapes multiply; string literals do not.
_ASSERT_RATCHET = re.compile(r"assert_ratchet\(")

#: Where the Python-side consumers live. Scoped rather than repo-wide so the
#: scan stays fast and so a stray mention in a doc or a test fixture cannot
#: register as enforcement.
_PY_CONSUMERS = ("odoo/addons/test_lint/tests",)

#: Floors measured over a sibling checkout, invoked from THAT repo's
#: `architecture.yml` (`--mode no-increase`) with this repo checked out beside
#: it. CI here checks this repository out alone and cannot see those workflows,
#: so they are named rather than discovered. The pin stays in `odoo` on purpose
#: — one floor cannot drift out of step with itself, two would — which is the
#: arrangement `tooling/README.md` describes for the cross-repo gates.
ENFORCED_BY_A_SIBLING: frozenset[str] = frozenset(
    {
        "py_count_as_boolean_agromarin",
        "py_count_as_boolean_enterprise",
        "py_x2many_count_agromarin",
        "py_x2many_count_enterprise",
        "sql_in_placeholder_agromarin",
        "sql_in_placeholder_enterprise",
    }
)


def recorded_floors() -> set[str]:
    return {path.stem for path in BASELINES_DIR.glob("*.json")}


def invoked_gates() -> set[str]:
    """Floors a CI workflow runs as a shell step."""
    found: set[str] = set()
    for path in sorted(WORKFLOWS.glob("*.yml")):
        text = _COMMENT_LINE.sub("", path.read_text(encoding="utf-8"))
        found.update(_INVOCATION.findall(_CONTINUATION.sub(" ", text)))
    return found


def _py_consumer_files() -> list[Path]:
    return [
        path
        for rel in _PY_CONSUMERS
        if (ROOT / rel).is_dir()
        for path in sorted((ROOT / rel).rglob("*.py"))
    ]


def asserted_gates() -> set[str]:
    """Floors named by a Python caller that loads them through `Baseline.load`.

    Every string literal in those modules, plus the gate each literal would
    DERIVE. Three discovery rules were tried here and the first two were wrong,
    in the same direction each time — reporting live floors as orphans:

    1. Match the call, `assert_ratchet(findings, "<gate>", …)`. Defeated by
       `test_xml_records.py`, which reaches it through a local `_assert_clean`
       wrapper.
    2. Read every string literal instead, from the syntax tree. Defeated by
       `_rules.Rule.gate`, which is `"lint_" + self.name.replace("-", "_")` — the
       gate name appears nowhere; the RULE name (`"sql-injection"`) does.
    3. Read the literals and apply that transform to each. Shapes multiply and
       names are derived; a rule that only ever spells `sql-injection` still
       accounts for `lint_sql_injection`.

    The cost of over-generating is that a floor could be matched by an unrelated
    literal that happens to underscore into its name. That direction is safe: it
    can only fail to report an orphan, never invent one, and the mirror test
    (every workflow invocation names a real floor) has no such slack.
    """
    found: set[str] = set()
    for path in _py_consumer_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                found.add(node.value)
                found.add("lint_" + node.value.replace("-", "_"))
    return found


def enforced_gates() -> set[str]:
    return invoked_gates() | asserted_gates()


def test_the_discovery_finds_something():
    # Every assertion below passes by finding nothing if either half breaks --
    # the workflows moving, or the glob pattern going stale.
    assert len(recorded_floors()) > 20, f"only {len(recorded_floors())} baselines found"
    assert len(invoked_gates()) > 20, (
        f"only {len(invoked_gates())} ratchet invocations found under {WORKFLOWS} — "
        f"the discovery rule is broken, not the workflows"
    )
    files = _py_consumer_files()
    assert files, f"no Python consumer found under {_PY_CONSUMERS}"
    calls = sum(
        len(_ASSERT_RATCHET.findall(p.read_text(encoding="utf-8"))) for p in files
    )
    assert calls, (
        f"no `assert_ratchet(` call under {', '.join(_PY_CONSUMERS)} — the "
        f"Python-side consumer moved, and every floor it holds would read as "
        f"unenforced"
    )
    assert asserted_gates(), "the literal scan found nothing"


@pytest.mark.parametrize("gate", sorted(recorded_floors()))
def test_every_floor_is_read_by_some_consumer(gate):
    if gate in ENFORCED_BY_A_SIBLING:
        return
    assert gate in enforced_gates(), (
        f"baselines/{gate}.json is read by nothing — no workflow step in "
        f"{WORKFLOWS.name}/ and no `assert_ratchet` call under "
        f"{', '.join(_PY_CONSUMERS)}. A floor nothing runs is debt that reads "
        f"as governed: wire it into a lane, delete it, or — if a sibling repo's "
        f"CI owns it — add it to ENFORCED_BY_A_SIBLING with the workflow that "
        f"does."
    )


@pytest.mark.parametrize("gate", sorted(invoked_gates()))
def test_every_workflow_invocation_names_a_recorded_floor(gate):
    """Only the WORKFLOW consumer. The Python one treats absence as zero.

    `ratchet.py <gate> --count N` with no baseline exits 2 and says so, so a
    typo there is a lane that cannot run. `LintCase.assert_ratchet` is the
    opposite by design — `baseline_floor` returns 0 for an unknown gate, and its
    docstring says why: "a gate nobody has had to grant debt to is a gate at
    zero, and promoting one costs an explicit `--update`, which shows up in
    review". Asserting a baseline for every `assert_ratchet` name would demand a
    file for every gate that is already clean, which is the opposite of what
    that design wants.

    This test asserted exactly that at first, and reported twenty gates as
    broken that were merely at zero.
    """
    assert gate in recorded_floors(), (
        f"a workflow runs `ratchet.py {gate} --count`, which has no "
        f"baselines/{gate}.json. That lane exits 2 on `error: no baseline`; if "
        f"the name is a typo, the floor it meant to move is still drifting "
        f"under its real name."
    )


def test_no_sibling_pin_has_gone_stale():
    ghosts = ENFORCED_BY_A_SIBLING - recorded_floors()
    assert not ghosts, (
        f"{sorted(ghosts)} are excused as sibling-enforced but have no baseline "
        f"file. Remove them, or restore the floor they name."
    )
    here = ENFORCED_BY_A_SIBLING & enforced_gates()
    assert not here, (
        f"{sorted(here)} are excused as sibling-enforced but this repo now "
        f"reads them itself. Drop them from ENFORCED_BY_A_SIBLING so they are "
        f"checked like every other floor."
    )


def test_every_baseline_parses_as_a_floor():
    # `--list` reports a broken file and exits 2, but only when someone runs it.
    for path in sorted(BASELINES_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(data.get("count"), int), f"{path.name}: count is not an int"
        assert data["count"] >= 0, f"{path.name}: negative floor {data['count']}"
        assert data.get("note", "").strip(), (
            f"{path.name} carries no note. Every floor records what moved it and "
            f"why — that is the only account of the number a reviewer gets."
        )

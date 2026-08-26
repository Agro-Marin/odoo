from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _consumer_scopes as cs

_RUNS = re.compile(r"tooling/architecture/(\w+)\.py")


def _sibling_workflow(scope: str) -> Path | None:
    for name, root in cs.CONSUMER_ROOTS:
        if name == scope:
            path = root / ".github" / "workflows" / "architecture.yml"
            return path if path.is_file() else None
    return None


def _scopes_other_than_odoo() -> list[str]:
    return [name for name, _root in cs.CONSUMER_ROOTS if name != "odoo"]


def test_every_governed_gate_declares_a_row():
    here = Path(__file__).resolve().parent
    printers = {
        p.stem
        for p in here.glob("*.py")
        if not p.stem.startswith(("test_", "_"))
        and "absent_scopes_line" in p.read_text(encoding="utf-8")
    }
    assert printers, "no gate calls absent_scopes_line — the probe found nothing"
    missing = printers - set(cs.VALIDATED_BY)
    assert not missing, (
        f"{sorted(missing)} print the absent-scope line but declare no row in "
        f"VALIDATED_BY. An empty dict is a real answer ('no lane judges this "
        f"gate's sibling scopes'); a missing key is an oversight that reads the "
        f"same way."
    )


@pytest.mark.parametrize("gate", sorted(cs.VALIDATED_BY))
def test_the_declared_lanes_really_run_the_gate(gate):
    for scope, workflow_rel in cs.VALIDATED_BY[gate].items():
        workflow = _sibling_workflow(scope)
        if workflow is None:
            pytest.skip(f"{scope} is not checked out beside this repo")
        assert workflow_rel.endswith("architecture.yml"), workflow_rel
        runs = set(_RUNS.findall(workflow.read_text(encoding="utf-8")))
        assert gate in runs, (
            f"VALIDATED_BY says {workflow_rel} re-runs {gate} for the {scope} "
            f"scope, and it does not. Either that lane lost the step — in which "
            f"case the scope's rows in the pin are now judged by nothing — or "
            f"the table is stale."
        )


@pytest.mark.parametrize("gate", sorted(cs.VALIDATED_BY))
def test_no_lane_is_missing_from_the_table(gate):
    for scope in _scopes_other_than_odoo():
        workflow = _sibling_workflow(scope)
        if workflow is None:
            continue
        runs = set(_RUNS.findall(workflow.read_text(encoding="utf-8")))
        if gate in runs and scope not in cs.VALIDATED_BY[gate]:
            pytest.fail(
                f"{scope}'s architecture.yml runs {gate}, but VALIDATED_BY does "
                f"not say so — add the row so the gate stops calling that scope "
                f"unjudged."
            )


def test_the_unjudged_list_is_exactly_what_no_lane_covers():
    judged = {scope for lanes in cs.VALIDATED_BY.values() for scope in lanes}
    for scope in _scopes_other_than_odoo():
        workflow = _sibling_workflow(scope)
        if workflow is None:
            continue
        if _RUNS.findall(workflow.read_text(encoding="utf-8")):
            judged.add(scope)
    stale = cs.UNJUDGED_SCOPES & judged
    assert not stale, (
        f"{sorted(stale)} are listed as judged by no lane, but a workflow now "
        f"runs architecture gates for them. Remove them from UNJUDGED_SCOPES."
    )


def test_the_absent_line_never_claims_coverage_it_cannot_show():
    unjudged = cs.absent_scopes_line("js_public_surface", ["no-such-consumer"])
    assert "NO lane" in unjudged
    assert "validated in their own CI" not in unjudged

    judged = cs.absent_scopes_line("js_public_surface", ["enterprise"])
    assert "architecture.yml" in judged and "NO lane" not in judged

    both = cs.absent_scopes_line(
        "js_public_surface", ["enterprise", "no-such-consumer"]
    )
    assert "NO lane" in both and "architecture.yml" in both
    assert "enterprise" not in both.split("NO lane")[1]


def test_no_scope_is_pinned_without_a_lane_today():
    judged = {scope for lanes in cs.VALIDATED_BY.values() for scope in lanes}
    uncovered = {
        name
        for name, _root in cs.CONSUMER_ROOTS
        if name != "odoo" and name not in judged and name not in cs.UNJUDGED_SCOPES
    }
    assert not uncovered, (
        f"{sorted(uncovered)} consume `web` and appear in the pins, but no gate "
        f"declares a lane for them and they are not listed as unjudged. Add the "
        f"lane, or declare the hole in UNJUDGED_SCOPES so the gates stop "
        f"claiming coverage."
    )


def test_the_roots_are_shared_not_copied():
    here = Path(__file__).resolve().parent
    copies = [
        p.name
        for p in sorted(here.glob("*.py"))
        if p.stem != "_consumer_scopes"
        and not p.stem.startswith("test_")
        and re.search(r'CONSUMER_ROOTS\s*=\s*\(\s*\n\s*\("odoo"', p.read_text("utf-8"))
    ]
    assert not copies, (
        f"{copies} still declare CONSUMER_ROOTS inline. Import it from "
        f"_consumer_scopes so the scope list and the lane table cannot disagree."
    )

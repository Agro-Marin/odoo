"""The survey's mapping must cover every floor, or the survey lies by omission.

`survey.py` exists because nothing turned a floor name into the command that
measures it, and 12 of 41 measurable floors were found drifted the day it was
written. Its one structural risk is that the mapping rots as floors are added:
a new baseline nobody maps is a floor the survey silently stops covering, which
is the original failure with an extra layer on top.

So this module asserts the mapping is total and honest, and nothing about the
counts. A floor being above its floor is `ratchet.py`'s verdict to give, not
this file's -- these tests must stay green while the tree is red.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ratchet
import survey


def _baselines() -> set[str]:
    return {p.stem for p in ratchet.BASELINES_DIR.glob("*.json")}


def test_every_baseline_is_mapped_or_explicitly_out_of_scope():
    # The lint family is delegated: sibling scopes to `py_lint.py --check`, the
    # odoo scope to a `-i test_lint` run. Everything else must be named.
    unmapped = {
        gate
        for gate in _baselines()
        if gate not in survey.RUNNERS
        and gate not in survey.UNCOVERED
        and not gate.startswith(("lint_", "bundle_"))
    }
    assert unmapped == set(), (
        f"these floors are in neither RUNNERS nor UNCOVERED, so the survey "
        f"reports them as 'unmapped' and measures nothing: {sorted(unmapped)}"
    )


def test_no_mapping_entry_is_dead_weight():
    # A runner for a floor that does not exist is the allowlist-that-hides-
    # nothing shape: it reads as coverage and is not.
    stale = (set(survey.RUNNERS) | set(survey.UNCOVERED)) - _baselines()
    assert stale == set(), (
        f"mapped but no baseline file exists -- a gate held at a hard zero has "
        f"no baseline and needs no runner here: {sorted(stale)}"
    )


def test_every_runner_names_a_script_that_exists():
    missing = {
        gate: script
        for gate, (script, _args) in survey.RUNNERS.items()
        if not (survey.ARCH / script).is_file()
    }
    assert missing == {}, f"runner script not found: {missing}"


def test_every_uncovered_entry_carries_a_reason():
    for gate, why in survey.UNCOVERED.items():
        assert len(why) > 15, f"{gate} is out of scope with no argument, only a string"


def test_the_no_increase_rule_matches_what_the_guidelines_state():
    # §9.2: every cross-repo scope is no-increase; on the odoo side
    # `pyfunclen_addons` is the only one. Encoded twice on purpose -- if the
    # rule moves, this fails rather than the survey quietly grading a floor in
    # the wrong mode, which over-reports and gets the tool ignored.
    assert survey.mode_for("naming_enterprise") == "no-increase"
    assert survey.mode_for("unresolved_calls_agromarin") == "no-increase"
    assert survey.mode_for("pyfunclen_addons") == "no-increase"
    assert survey.mode_for("pyclasslen_addons") == "exact"
    assert survey.mode_for("fieldhooks") == "exact"
    assert survey.mode_for("naming") == "exact"


def test_the_verdict_comes_from_the_ratchet_and_not_from_this_module():
    # Reimplementing the comparison is how a survey and the gate it surveys come
    # to disagree. A decrease is a failure under `exact` and fine under
    # `no-increase`, and only `ratchet.evaluate` is allowed to say so.
    lower = ratchet.Baseline(count=10)
    assert not ratchet.evaluate("x", 9, lower, "exact").ok
    assert ratchet.evaluate("x", 9, lower, "no-increase").ok
    assert not ratchet.evaluate("x", 11, lower, "no-increase").ok


def test_a_baseline_file_is_readable_json_with_a_count():
    for path in ratchet.BASELINES_DIR.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(data.get("count"), int), f"{path.name} has no integer count"


def test_the_dirty_tree_check_names_the_repos_it_will_scan():
    # The provenance banner is the module's only defence against its most
    # dangerous property -- that it measures wherever it is run, and the sibling
    # mappings make that invisible. It must consider the odoo root AND every
    # sibling scope, because `--roots ../enterprise` reads like a clean checkout
    # and silently names the live one.
    import inspect

    src = inspect.getsource(survey.dirty_trees)
    assert "SIBLING_SCOPES" in src, "the check must cover the siblings, not just odoo"
    assert "--porcelain" in src
    # It returns a mapping of repo -> count, empty when everything is clean.
    result = survey.dirty_trees()
    assert isinstance(result, dict)
    assert all(isinstance(v, int) and v > 0 for v in result.values())

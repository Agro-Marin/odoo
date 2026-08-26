from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "architecture"))
from _repo_root import find_odoo_root

ROOT = find_odoo_root(Path(__file__).resolve(), tool="test_ci_lanes")
WORKFLOWS = ROOT / ".github" / "workflows"
SELFTEST = WORKFLOWS / "tooling_selftest.yml"
HERE = Path(__file__).resolve().parent


def _pull_request_block(workflow: Path) -> str:
    text = workflow.read_text(encoding="utf-8")
    after = text.split("pull_request:", 1)
    assert len(after) == 2, f"{workflow.name} has no pull_request trigger"
    return re.split(r"^\w", after[1], maxsplit=1, flags=re.MULTILINE)[0]


def test_the_selftest_lane_runs_the_whole_directory():
    assert "pytest tooling/" in SELFTEST.read_text(encoding="utf-8")


def test_the_selftest_lane_has_no_path_filter():
    block = _pull_request_block(SELFTEST)
    globs = re.findall(r"^\s*- '([^']+)'", block, re.MULTILINE)
    branch_globs = {"*", "19.0", "19.0-marin"}
    paths = [g for g in globs if g not in branch_globs]
    assert not paths, (
        f"tooling_selftest.yml filters its pull_request trigger to {paths}. "
        f"This suite measures the repository, not `tooling/` — see "
        f"test_the_suite_really_does_read_outside_tooling below — so any filter "
        f"is a scope claim that will be wrong, and a wrong one means the lane "
        f"reports nothing on the PR that breaks it. `598cf211cc2` is the "
        f"worked example: it touched `odoo/addons/base/i18n/base.pot` alone, "
        f"matched none of the old globs, and landed red."
    )


def test_the_suite_really_does_read_outside_tooling():
    import translation_catalog

    pots = [pot for _module, _dir, pot in translation_catalog.iter_modules()]
    assert pots, "no catalogue found — the probe reached nothing"
    outside = [p for p in pots if not p.is_relative_to(HERE)]
    assert outside, "translation_catalog no longer reads outside tooling/"

    base_pot = ROOT / "odoo" / "addons" / "base" / "i18n" / "base.pot"
    assert base_pot in pots, (
        f"{base_pot.relative_to(ROOT)} is not among the catalogues this suite "
        f"reads, yet regenerating it is what broke the lane. If the gate's "
        f"scope really changed, re-derive this test rather than deleting it."
    )


@pytest.mark.parametrize("workflow", ["architecture.yml", "tooling_selftest.yml"])
def test_the_mainline_trigger_is_never_filtered(workflow):
    text = (WORKFLOWS / workflow).read_text(encoding="utf-8")
    push_block = text.split("push:", 1)[1].split("pull_request:", 1)[0]
    assert "paths:" not in push_block, (
        f"{workflow} filters its push: trigger; mainline must be re-checked in full"
    )

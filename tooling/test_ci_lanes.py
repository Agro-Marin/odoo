"""The CI lanes that run this directory, checked against what it actually reads.

A workflow's `paths:` filter is a claim about scope, and a wrong one fails
open: the lane reports nothing on the pull request and the breakage lands, to
be discovered by the post-merge `push:` trigger after the merge-blocking checks
have already gone green.

`architecture.yml` learnt this and says so in its own header — it replaced a
per-package enumeration with `odoo/**` + `addons/**` because "the list is a
second, hand-maintained copy of every checker's scope, and it silently rots as
packages are added", and `test_ci_path_filter_covers_every_scanned_tree`
(tooling/architecture/test_architecture_doc.py) pins that one.

`tooling_selftest.yml` had the same shape and the same fault, unpinned. This is
its half of the pair.
"""

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
    # The trigger block ends at the next top-level key.
    return re.split(r"^\w", after[1], maxsplit=1, flags=re.MULTILINE)[0]


def test_the_selftest_lane_runs_the_whole_directory():
    # Everything below is about WHEN the lane runs; this pins THAT it runs, so
    # a rename of the pytest target cannot make the rest vacuous.
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
    """The reason the filter has to go, asserted rather than narrated.

    Without this, the test above is a style rule. With it, removing the filter
    is a consequence of what the suite measures — and if some future refactor
    genuinely confines these tests to `tooling/`, this fails first and says the
    filter may come back.
    """
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
    # Both lanes re-verify the protected branches in full on push. A filter
    # there would let a direct commit or a merge skew past the gate entirely,
    # which is the failure the pull_request filter only delays.
    text = (WORKFLOWS / workflow).read_text(encoding="utf-8")
    push_block = text.split("push:", 1)[1].split("pull_request:", 1)[0]
    assert "paths:" not in push_block, (
        f"{workflow} filters its push: trigger; mainline must be re-checked in full"
    )

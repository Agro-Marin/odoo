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

TOOLCHAIN_GATES: frozenset[str] = frozenset(
    {
        "js_arch_info_surface",
        "js_field_record_surface",
        "js_function_length",
        "js_mixin_coupling",
        "js_patch_blind_facade",
        "js_service_shape",
        "js_template_binding",
        "xml_reference_coherence",
    }
)


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


_PYTEST_TARGET = re.compile(r"pytest\s+(tooling/[\w/]*)")

TOOLCHAIN_SUITE_DIR = "tooling/architecture"


def _suite_paths(workflow: Path) -> list[str]:
    return _PYTEST_TARGET.findall(workflow.read_text(encoding="utf-8"))


def _needs_toolchain(paths: list[str]) -> bool:
    return any(
        stem == TOOLCHAIN_SUITE_DIR or TOOLCHAIN_SUITE_DIR.startswith(f"{stem}/")
        for stem in (path.rstrip("/") for path in paths)
    )


def _lanes_running_a_toolchain_suite() -> list[Path]:
    return [
        path
        for path in sorted(WORKFLOWS.glob("*.yml"))
        if _needs_toolchain(_suite_paths(path))
    ]


def test_the_toolchain_lane_discovery_finds_something():
    lanes = _lanes_running_a_toolchain_suite()
    assert lanes, (
        f"no workflow under {WORKFLOWS} runs a pytest path covering the "
        f"{len(TOOLCHAIN_GATES)} node-dependent suites, so the check below "
        f"would pass by finding nothing"
    )
    assert SELFTEST in lanes, (
        f"{SELFTEST.name} runs the whole directory and must be in this set; "
        f"the discovery rule is broken, not the workflow"
    )


@pytest.mark.parametrize(
    "workflow", [p.name for p in _lanes_running_a_toolchain_suite()]
)
def test_a_lane_running_a_toolchain_suite_installs_the_toolchain(workflow):
    text = (WORKFLOWS / workflow).read_text(encoding="utf-8")
    assert "actions/setup-node" in text and "npm ci" in text, (
        f"{workflow} runs a pytest path that includes the "
        f"{len(TOOLCHAIN_GATES)} node-dependent gate suites, without "
        f"`actions/setup-node` and `npm ci`. Those gates shell out to the JS "
        f"toolchain and resolve it from `node_modules/`, which is gitignored, "
        f"so their suites raise ERR_MODULE_NOT_FOUND on a clean checkout. "
        f"Measured on one worktree at one commit: 0 failed with `node_modules` "
        f"present, 107 failed without it, across seven suites. A lane that "
        f"cannot run the tests it names reports a missing tool as a finding."
    )


def test_the_toolchain_gate_list_still_matches_the_tree():
    architecture = HERE / "architecture"
    reaching = set()
    for path in sorted(architecture.glob("*.py")):
        if path.stem.startswith("test_"):
            continue
        source = path.read_text(encoding="utf-8")
        if "subprocess.run" in source and ('"node"' in source or "ESLINT" in source):
            reaching.add(path.stem)
    assert reaching == TOOLCHAIN_GATES, (
        f"the set of gates that shell out to node has moved: "
        f"unlisted {sorted(reaching - TOOLCHAIN_GATES)}, "
        f"stale {sorted(TOOLCHAIN_GATES - reaching)}. Update TOOLCHAIN_GATES -- "
        f"it is what decides which lanes the check above applies to."
    )


UNIT_TESTS = WORKFLOWS / "unit_tests.yml"

TIER_2 = (
    "odoo/orm/tests",
    "odoo/http/tests",
    "odoo/db/tests",
    "odoo/tools/tests",
    "tests/service",
    "tests/framework",
)


def _testpaths() -> list[str]:
    block = (ROOT / "pytest.ini").read_text(encoding="utf-8").split("testpaths =", 1)
    assert len(block) == 2, "pytest.ini has no testpaths"
    return re.findall(r"^    (\S+)$", block[1], re.MULTILINE)


def _filter_globs(workflow: Path) -> list[str]:
    block = _pull_request_block(workflow)
    after = block.split("paths:", 1)
    if len(after) == 1:
        return []
    return re.findall(r"^\s*- '([^']+)'", after[1], re.MULTILINE)


def _source_of(suite: str) -> str:
    return suite.removesuffix("/tests")


def _covered(source: str, globs: list[str]) -> bool:
    probe = f"{source}/x.py"
    return any(
        probe == g or probe.startswith(g.rstrip("*").rstrip("/") + "/") for g in globs
    )


def test_the_testpaths_and_filter_are_both_readable():
    assert len(_testpaths()) > 15, _testpaths()
    assert len(_filter_globs(UNIT_TESTS)) > 5, _filter_globs(UNIT_TESTS)
    assert _covered("odoo/libs", ["odoo/libs/**"])
    assert _covered("odoo/orm/domain", ["odoo/orm/**"])
    assert not _covered("odoo/tools", ["odoo/orm/**", "odoo/libs/**"])


def test_every_suite_this_lane_runs_is_triggered_by_its_own_source():
    globs = _filter_globs(UNIT_TESTS)
    missing = sorted(
        {
            _source_of(suite)
            for suite in [*_testpaths(), *TIER_2]
            if not _covered(_source_of(suite), globs)
        }
    )
    assert not missing, (
        "unit_tests.yml runs a suite for each of these trees, but its "
        "pull_request `paths:` filter does not name them, so changing one does "
        "not run its own tests:\n  "
        + "\n  ".join(missing)
        + "\n\nAdd each to the filter, or move the suite to a lane that covers "
        "it."
    )


@pytest.mark.parametrize("suite", TIER_2)
def test_the_tier_2_paths_are_still_the_ones_the_lane_invokes(suite):
    assert suite in UNIT_TESTS.read_text(encoding="utf-8"), (
        f"{suite} is listed here as a Tier-2 path but unit_tests.yml no longer "
        f"invokes it; this gate is now checking a suite nothing runs"
    )

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import _sources
from _repo_root import find_odoo_root

ROOT = find_odoo_root(Path(__file__).resolve(), tool="test_sources")
TOOLING = ROOT / "tooling"

KNOWN_POLYGLOTS = {
    "bench/discuss_bench",
    "bench/render_bench",
    "hoot/hoot",
    "hoot/hoot-affected",
    "hoot/hoot-shard",
}


def _found_polyglots() -> set[str]:
    return {
        path.relative_to(TOOLING).as_posix()
        for path in TOOLING.rglob("*")
        if _sources.is_polyglot(path)
    }


def test_every_polyglot_runner_is_found():
    assert _found_polyglots() == KNOWN_POLYGLOTS


def test_the_marker_is_not_on_the_line_the_first_attempt_looked_at():
    runner = TOOLING / "hoot" / "hoot"
    lines = runner.read_text(encoding="utf-8").splitlines()
    marker_at = next(
        i for i, line in enumerate(lines) if line.startswith(_sources.POLYGLOT_MARKER)
    )
    assert marker_at >= 2, "the prologue changed; a two-line window would now work"
    assert marker_at < _sources.POLYGLOT_PROLOGUE_LINES


def test_a_plain_shell_script_is_not_python(tmp_path):
    script = tmp_path / "deploy"
    script.write_text("#!/bin/sh\necho hello\n", encoding="utf-8")
    assert not _sources.is_polyglot(script)


def test_an_unreadable_path_is_not_python(tmp_path):
    assert not _sources.is_polyglot(tmp_path / "does_not_exist")
    assert not _sources.is_polyglot(tmp_path)


def test_polyglots_can_be_excluded_without_disturbing_the_py_set():
    with_them = _sources.iter_python_files(TOOLING)
    without = _sources.iter_python_files(TOOLING, include_polyglots=False)
    assert set(with_them) - set(without) == {
        TOOLING / rel for rel in KNOWN_POLYGLOTS
    }


def test_tests_are_excluded_by_default_and_reachable_on_request():
    default = _sources.iter_python_files(TOOLING)
    assert not [p for p in default if _sources.is_test_path(p)]
    everything = _sources.iter_python_files(TOOLING, include_tests=True)
    assert [p for p in everything if _sources.is_test_path(p)]


def test_the_rule_does_not_move_what_pyfunclen_already_measures():
    scope = ROOT / "odoo"
    before = {
        path
        for path in scope.rglob("*.py")
        if "__pycache__" not in path.parts and not _sources.is_test_path(path)
    }
    after = set(_sources.iter_python_files(scope))
    assert after == before, {
        "added": sorted(str(p) for p in after - before),
        "dropped": sorted(str(p) for p in before - after),
    }


def test_display_falls_back_to_absolute_outside_the_root():
    inside = ROOT / "odoo" / "orm" / "models.py"
    assert _sources.display(inside, ROOT) == "odoo/orm/models.py"
    outside = Path("/somewhere/else/agromarin/models/thing.py")
    assert _sources.display(outside, ROOT) == str(outside)


def test_no_gate_redeclares_the_shared_helpers():
    here = Path(__file__).resolve().parent
    offenders = []
    for path in sorted(here.glob("*.py")):
        if path.stem.startswith("test_") or path.stem == "_sources":
            continue
        text = path.read_text(encoding="utf-8")
        offenders.extend(
            f"{path.name}: {name.removeprefix('def ')})"
            for name in ("def _is_test_path(", "def _display(")
            if name in text
        )
    assert not offenders, (
        f"these re-declare a helper `_sources` already owns: {offenders}. Import "
        f"it, or -- if the behaviour must differ -- name the function for what "
        f"makes it different so the divergence is visible."
    )

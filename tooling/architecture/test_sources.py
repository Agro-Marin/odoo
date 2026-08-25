"""The discovery rule every Python gate walks on.

Two properties matter. The polyglot runners must be FOUND — they are 1,647 lines
of real Python that `rglob("*.py")` cannot see, and `ruff.toml` had to name them
one by one to close the same hole for the linter. And the rule must not quietly
change what an existing floor measures: `pyfunclen` is an exact ratchet over
`odoo/`, so a discovery change that adds or drops one file there moves a number
nobody asked to move.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import _sources
from _repo_root import find_odoo_root

# `find_odoo_root`, not `parents[2]`: the depth is right today and silently wrong
# the moment a file moves, and `test_repo_root` refuses parent-counting for that
# reason.
ROOT = find_odoo_root(Path(__file__).resolve(), tool="test_sources")
TOOLING = ROOT / "tooling"

#: The five that exist today. Named here and DISCOVERED in the module, so the
#: test fails in both directions: a runner that stops being found, and a sixth
#: that lands without anyone noticing it is now measured.
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
    """Why `POLYGLOT_PROLOGUE_LINES` is 10 and not 2.

    The prologue is a shebang, a `ruff format` directive, a `# fmt: off` and only
    then the marker. Reading two lines found none of the five and reported a
    clean zero, which is the failure mode the whole module is about.
    """
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
    """A floored scope must see exactly the files it saw before.

    `pyfunclen` is exact over `odoo/`. This reproduces the pre-`_sources` rule
    and asserts the sets agree, so adding polyglot discovery cannot move that
    floor by a file. Measured when the rule landed: 543 both ways, no additions,
    no drops.
    """
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
    """The duplication this module was written to end, kept ended.

    Six gates carried `_is_test_path` byte-identically and seven carried
    `_display`. A gate that needs different behaviour should say so by not
    importing, not by forking a copy that drifts silently -- which is how
    `py_unresolved_calls` came to count test files while its four siblings did
    not, with nothing recording whether that was deliberate.
    """
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

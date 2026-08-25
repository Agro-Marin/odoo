"""`--help` says what the gate is for, or the README is lying.

`tooling/README.md`: *"Each gate documents itself in its module docstring; run any
of them with `--help`."* `doc/architecture/ARCHITECTURE.md` routes a reader the
same way -- *"wondering why a rule exists → `doc/adr/`, then the gate's own module
docstring"*. Both were false for 22 of the 60 gates here, which pass
`description=__doc__` to argparse with `__doc__` set to `None`, so `--help`
printed usage, flags, and no statement of what the gate checks or why.

That matters at the moment it is read. A gate fails a build, someone who did not
write it runs it with `--help`, and either learns the rule or goes looking for
the ADR. The newer gates carry excellent docstrings; the older ones carry none,
and the difference is invisible until you need one.

Pinned rather than fixed in one sweep, in the shape
`test_gate_adr_coverage.UNRECORDED_GATES` already uses: the omission is visible
and owed, and the list can only shrink.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

HERE = Path(__file__).resolve().parent

#: Gates whose `--help` still prints no description. Every entry is debt: write
#: the docstring and delete the line. NOTHING may be added -- a new gate arrives
#: with its rationale or it does not arrive.
#:
#: Four were paid down when this test landed (2026-08-25) --
#: `named_export_coherence`, `py_function_length`, `py_unresolved_calls` and
#: `js_public_surface` -- chosen because they had just been read closely enough
#: to describe truthfully. A docstring written from a guess is worse than none:
#: it reads as authority.
UNDOCUMENTED: frozenset[str] = frozenset(
    {
        "cross_repo_coherence",
        "doc_restated_counts",
        "js_cycle_check",
        "js_deployment_layers",
        "js_face_boundary",
        "js_forced_render",
        "js_function_length",
        "js_import_resolution",
        "js_layer_check",
        "js_layer_cohesion",
        "js_patch_blind_facade",
        "js_registry_layering",
        "js_self_bridge",
        "js_service_shape",
        "js_suite_parity",
        "layer_check",
        "named_export_coherence_placeholder_never_matches",
        "naming_vocabulary",
        "py_cycle_check",
        "xml_reference_coherence",
    }
    - {"named_export_coherence_placeholder_never_matches"}
)

#: Gates that pass a hand-written one-liner instead of `__doc__`. Their `--help`
#: is not empty, so they are not the same debt -- but a line is not the rationale
#: the README promises either, and they are named here so the distinction is
#: recorded rather than lost between the two sets.
ONE_LINE_DESCRIPTION: frozenset[str] = frozenset(
    {
        "env_model_surface_check",
        "env_surface_check",
        "libs_facade_check",
        "py_cycle_check",
        "worker_thread_surface_check",
    }
)


def gate_modules() -> list[Path]:
    """Every gate here, by the same rule `test_gate_adr_coverage` uses."""
    found = []
    for path in sorted(HERE.glob("*.py")):
        if path.name.startswith(("test_", "_")):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if any(isinstance(n, ast.FunctionDef) and n.name == "main" for n in tree.body):
            found.append(path)
    return found


def _undocumented() -> set[str]:
    return {
        path.stem
        for path in gate_modules()
        if not ast.get_docstring(ast.parse(path.read_text(encoding="utf-8")))
    }


def test_the_gate_list_is_not_empty():
    assert len(gate_modules()) > 20, (
        f"only {len(gate_modules())} gates found in {HERE} — the discovery rule "
        f"is broken, and every check here would pass by finding nothing."
    )


def test_no_new_gate_arrives_without_a_docstring():
    new = _undocumented() - UNDOCUMENTED - ONE_LINE_DESCRIPTION
    assert not new, (
        f"{sorted(new)} declare a `main()` and no module docstring, so their "
        f"`--help` prints no description. Write it -- what the gate checks, and "
        f"why the rule exists -- or say why it is deferred by adding the name to "
        f"UNDOCUMENTED, which is a list that is supposed to shrink."
    )


def test_the_pinned_list_shrinks_and_never_grows():
    written = UNDOCUMENTED - _undocumented()
    assert not written, (
        f"{sorted(written)} now carry a docstring. Good — remove them from "
        f"UNDOCUMENTED so the debt cannot drift back up."
    )


def test_a_stale_pin_cannot_hide_a_deleted_gate():
    present = {p.stem for p in gate_modules()}
    ghosts = (UNDOCUMENTED | ONE_LINE_DESCRIPTION) - present
    assert not ghosts, (
        f"{sorted(ghosts)} are pinned here but are no longer gates in this "
        f"directory. Remove them."
    )


@pytest.mark.parametrize(
    "gate", sorted({p.stem for p in gate_modules()} - frozenset(UNDOCUMENTED))
)
def test_a_documented_gate_actually_reaches_argparse(gate):
    """A docstring that `--help` cannot print is not documentation.

    The two halves are separable: a gate can carry a fine module docstring and
    still pass a hand-written `description=`, in which case the docstring is
    dead text. This asserts the wiring, not just the presence.
    """
    src = (HERE / f"{gate}.py").read_text(encoding="utf-8")
    if gate in ONE_LINE_DESCRIPTION:
        return
    assert "description=__doc__" in src, (
        f"{gate} has a module docstring that argparse never shows. Pass "
        f"`description=__doc__`, or add it to ONE_LINE_DESCRIPTION and say why "
        f"a hand-written line is the better one here."
    )

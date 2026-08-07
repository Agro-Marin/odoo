"""Every gate in this directory must refuse an empty tree, not pass on it.

Stdlib + pytest only — no Odoo imports — so this runs in the same
database-free way as the checkers themselves. Run with:

    pytest tooling/architecture/test_every_gate_refuses_an_empty_tree.py

This is the bug class, not a bug. `cross_repo_coherence` shipped it three times
(1cd6f1667ba); 61aa19e2712 then swept the directory and fixed four more. That
sweep was manual and it cleared `js_layer_cohesion`, which was wrong: it probed
an ABSENT tree, and that gate's guard tested `src/`.is_dir(), so absence did
refuse. Present-and-empty — the case a bad exclude or glob actually produces, as
tsconfig.json's `**/l10n*` produced it — still passed with a clean ✓.

So the probe is parametrized over every gate rather than written per gate: a
gate added tomorrow is covered the day it lands, and against the harder of the
two empty shapes. A gate that cannot be probed belongs in `UNPROBED` with a
reason, where it is visible, rather than silently absent from the sweep.

**Subprocess, not monkeypatch.** The first version of this file redirected each
gate's module-level roots (`ROOT`, `WEB_SRC`, `ADDON_ROOTS`, ...) in-process.
That silently under-reached: `named_export_coherence` derives its scan roots
from `WORKSPACE` and `js_public_surface` from `WEB`/`CONSUMER_ROOTS`, neither of
which that list named, so both kept scanning the REAL tree and "failed" the
probe by legitimately passing on it. A probe that does not actually empty the
inputs is the same fault it is hunting, pointed the other way. Copying the
directory into a tmp root and running the gate as a subprocess exercises the
real `Path(__file__).parent.parent.parent` resolution, so a gate is emptied by
construction and no gate-internal names are hardcoded here.

`--check` is deliberate: a gate's exit code is the only part CI reads. Passing
the flag also pins that the flag exists, which is its own failure mode — report
mode exits 0 with violations printed, so a CI call site that forgets `--check`
gates on nothing.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent

# gate module -> argv proving the failure through the exit code CI reads.
GATES = {
    "js_cycle_check": ["--check"],
    "js_layer_check": ["--check"],
    "js_layer_cohesion": ["--check"],
    "js_registry_layering": ["--check"],
    "js_public_surface": ["--check"],
    "js_face_boundary": ["--check"],
    "js_import_resolution": ["--check"],
    "js_patch_blind_facade": ["--check"],
    "js_self_bridge": ["--check"],
    "js_suite_parity": ["--check"],
    "named_export_coherence": ["--check"],
    "layer_check": ["--check"],
    "js_private_access": ["--check"],
    "xml_reference_coherence": ["--check"],
    # No --check: it prints a count that feeds the shared ratchet. An empty scan
    # would report 0, and the ratchet runs in `exact` mode, so 0 against a floor
    # of 169 fails there instead. It must still refuse rather than print a
    # number nobody can tell from a real one.
    "js_function_length": ["--count"],
    # Same reasoning as js_function_length: a ratchet-fed count, no --check. An
    # empty scan would print 0 literal-shaped services, which reads exactly like
    # a tree that fixed all 33.
    "js_service_shape": ["--count"],
    # Same again for the §2.4 verb vocabulary: 0 abolished-verb definitions is
    # what a finished migration looks like, so an empty scan must refuse rather
    # than report one.
    "naming_vocabulary": ["--count"],
    # The Python core gates. They resolve inputs from `odoo/` packages rather
    # than the JS trees, so EMPTY_TREES creates those too — present-and-empty,
    # the harder of the two shapes.
    "env_surface_check": ["--check"],
    "env_model_surface_check": ["--check"],
    "pool_surface_check": ["--check"],
    "worker_thread_surface_check": ["--check"],
    "mixin_coupling_check": ["--check"],
    "libs_facade_check": ["--check"],
    "py_cycle_check": ["--check"],
    "package_index_check": ["--check"],
    "subsystem_map_check": ["--check"],
}

UNPROBED = {
    "js_imports": "a shared parser imported by the gates, not a gate — no main()",
    "cross_repo_coherence": (
        "takes an explicit --from/--to commit range rather than a tree; its own "
        "empty-range guard is what 1cd6f1667ba added, and "
        "test_cross_repo_coherence covers it directly"
    ),
}

# The trees a gate resolves inputs from, relative to the checkout root it
# derives from its own location. Created empty so every rglob finds nothing.
EMPTY_TREES = (
    "addons/web/static/src",
    "addons/web/static/tests",
    "odoo/addons",
    # The core packages the Python gates resolve their inputs from.
    "odoo/orm",
    "odoo/db",
    "odoo/libs",
    "odoo/tools",
    "odoo/http",
    "odoo/service",
    "odoo/modules",
    "odoo/tests",
)


def _checkout(tmp_path, *, litter=False):
    """A checkout whose gates are real and whose source trees are empty."""
    shutil.copytree(HERE, tmp_path / "tooling" / "architecture")
    for rel in EMPTY_TREES:
        tree = tmp_path / rel
        tree.mkdir(parents=True, exist_ok=True)
        if litter:
            (tree / "styles.scss").write_text("body { color: red; }\n")
            (tree / "README.md").write_text("not source\n")
    return tmp_path


def _run(root, gate):
    return subprocess.run(
        [sys.executable, str(root / "tooling" / "architecture" / f"{gate}.py")]
        + GATES[gate],
        capture_output=True,
        text=True,
        cwd=root,
        check=False,
    )


def test_every_gate_here_is_either_probed_or_excused():
    """No gate may drop out of the sweep by being forgotten."""
    found = {
        p.stem
        for p in HERE.glob("*.py")
        if not p.stem.startswith(("test_", "_")) and p.stem != "conftest"
    }
    assert found == set(GATES) | set(UNPROBED), (
        f"unswept: {sorted(found - set(GATES) - set(UNPROBED))}; "
        f"stale: {sorted((set(GATES) | set(UNPROBED)) - found)}"
    )


@pytest.mark.parametrize("gate", sorted(GATES))
def test_gate_refuses_a_present_but_empty_tree(gate, tmp_path):
    done = _run(_checkout(tmp_path), gate)
    assert done.returncode != 0, (
        f"{gate} exited 0 on a present-but-empty tree; a gate that finds no "
        f"inputs must refuse, not report success.\n{done.stdout}{done.stderr}"
    )


@pytest.mark.parametrize("gate", sorted(GATES))
def test_gate_refuses_a_tree_holding_only_non_source(gate, tmp_path):
    """A directory of .scss/.md is as empty as a bare one, and likelier."""
    done = _run(_checkout(tmp_path, litter=True), gate)
    assert done.returncode != 0, (
        f"{gate} exited 0 on a tree holding no JS.\n{done.stdout}{done.stderr}"
    )

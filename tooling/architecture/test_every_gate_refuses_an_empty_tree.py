import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent

GATES = {
    "js_component_data_access": ["--check"],
    "js_component_face": ["--check"],
    "js_cycle_check": ["--check"],
    "js_layer_check": ["--check"],
    "js_layer_cohesion": ["--check"],
    "js_deployment_layers": ["--check"],
    "js_registry_layering": ["--check"],
    "js_public_surface": ["--check"],
    "js_extension_surface": ["--check"],
    "js_env_config_surface": ["--check"],
    "js_arch_info_surface": ["--check"],
    "js_field_record_surface": ["--check"],
    "js_action_surface": ["--check"],
    "js_template_binding": ["--check"],
    "js_face_boundary": ["--check"],
    "js_import_resolution": ["--check"],
    "js_patch_blind_facade": ["--check"],
    "js_self_bridge": ["--check"],
    "js_forced_render": ["--check"],
    "js_suite_parity": ["--check"],
    "named_export_coherence": ["--check"],
    "layer_check": ["--check"],
    "js_private_access": ["--check"],
    "xml_reference_coherence": ["--check"],
    "js_function_length": ["--count"],
    "js_duplication": ["--count"],
    "js_vacuous_assertions": ["--count"],
    "py_function_length": ["--count"],
    "py_x2many_count": ["--count"],
    "sql_in_placeholder": ["--count"],
    "py_count_as_boolean": ["--count"],
    "py_unresolved_calls": ["--count"],
    "js_service_shape": ["--count"],
    "field_hook_naming": ["--count"],
    "field_hook_purity": ["--count"],
    "naming_vocabulary": ["--count"],
    # And for the order-line quantity gate: 0 writes of `product_uom_qty` is
    # what a tree that spells every ordered quantity `product_qty` looks like,
    # so an emptied one must refuse. Its guard is on finding no Python at all.
    "order_line_qty": ["--count"],
    # And for the catalogue gate: 0 unresolvable strings is what a tree whose
    # every `_()` was exported looks like, so an emptied one must refuse. Its
    # own guard is on finding no `.pot` at all rather than on the count.
    "translation_catalog": ["--count"],
    # And for the depends_context gate: 0 undeclared context reads is what a
    # tree that declared every key looks like, so an empty scan must refuse.
    "compute_context_deps": ["--count"],
    # The Python core gates. They resolve inputs from `odoo/` packages rather
    # than the JS trees, so EMPTY_TREES creates those too — present-and-empty,
    # the harder of the two shapes.
    "env_surface_check": ["--check"],
    "env_model_surface_check": ["--check"],
    "model_member_surface_check": ["--check"],
    "pool_surface_check": ["--check"],
    "worker_thread_surface_check": ["--check"],
    "mixin_coupling_check": ["--check"],
    "js_mixin_coupling": ["--check"],
    "mail_hook_keyword_check": ["--check"],
    "sql_placeholder": ["--check"],
    "libs_facade_check": ["--check"],
    "facade_surface_check": ["--check"],
    "py_cycle_check": ["--check"],
    "package_index_check": ["--check"],
    "subsystem_map_check": ["--check"],
    "doc_restated_counts": ["--check"],
    "edi_vocabulary": ["--check"],
}

UNPROBED = {
    "js_imports": "a shared parser imported by the gates, not a gate — no main()",
    "doc_measured": (
        "a helper the gates call to keep their own docstrings' figures honest, "
        "not a gate — no main(); test_doc_measured covers its refusals, "
        "including that a missing or pair-less MEASURED block raises rather "
        "than comparing equal to a gate that measured nothing"
    ),
    "cross_repo_coherence": (
        "takes an explicit --from/--to commit range rather than a tree; its own "
        "empty-range guard is what 1cd6f1667ba added, and "
        "test_cross_repo_coherence covers it directly"
    ),
}

EMPTY_TREES = (
    "addons/web/static/src",
    "addons/web/static/tests",
    "odoo/addons",
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
    # Skip __pycache__: it is 139 of this directory's 238 inodes and every one
    # is copied twice per gate. At 35 gates that is ~16k inodes a run, retained
    # for three runs by pytest's tmp_path policy, and it has exhausted /tmp's
    # inode table on this box. The subprocess recompiles what it imports.
    shutil.copytree(
        HERE,
        tmp_path / "tooling" / "architecture",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    # THE PROBE MUST REACH THE GATE'S LOGIC. Copying `tooling/architecture` alone
    # left `tooling/_repo_root.py` out of the tmp checkout, and 33 of the 37 gates
    # here import it -- so they died with ModuleNotFoundError before reading a
    # line of the emptied tree, exited non-zero, and satisfied an assertion that
    # only reads the exit code. The suite whose docstring warns that "a probe that
    # does not actually empty the inputs is the same fault it is hunting" was
    # running that fault one layer up, and it hid three gates that really do
    # report a clean zero on an empty tree.
    #
    # `find_odoo_root` locates the checkout by the `odoo-bin` marker, so the probe
    # needs that too or every gate refuses on the marker instead of on its inputs.
    shutil.copy2(HERE.parent / "_repo_root.py", tmp_path / "tooling")
    (tmp_path / "odoo-bin").write_text("#!/usr/bin/env python3\n")
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
    found = {
        p.stem
        for p in HERE.glob("*.py")
        if not p.stem.startswith(("test_", "_")) and p.stem != "conftest"
    }
    assert found == set(GATES) | set(UNPROBED), (
        f"unswept: {sorted(found - set(GATES) - set(UNPROBED))}; "
        f"stale: {sorted((set(GATES) | set(UNPROBED)) - found)}"
    )


#: Gates that raise instead of refusing when their inputs are absent. Every one
#: still exits non-zero, so none of them reports success over an empty tree --
#: the property this file was written for holds. What they do not do is SAY why,
#: and a traceback is what a broken gate looks like too, which is the whole point
#: of the discriminator below.
#:
#: Pinned rather than fixed in one sweep, and the list may only shrink. The fix
#: for one of these is a guard at the top of `measure`/`check` in the shape the
#: other fifty already use: name the tree, say the scan reached nothing, and note
#: that finding nothing is not the same as finding nothing wrong.
CRASHES_INSTEAD_OF_REFUSING = frozenset(
    {
        "doc_restated_counts",
        "env_surface_check",
        "js_action_surface",
        "js_arch_info_surface",
        "js_duplication",
        "js_env_config_surface",
        "js_field_record_surface",
        "mixin_coupling_check",
        "subsystem_map_check",
        "worker_thread_surface_check",
    }
)


def _assert_refuses(gate, done, what):
    """Non-zero is necessary and not sufficient: it must be a REFUSAL.

    A crash exits non-zero too, so a broken gate satisfies the exit code alone.
    A traceback in stderr is the discriminator: a gate that refuses does so
    deliberately and says why, in a sentence.

    WHAT THIS DOES AND DOES NOT CATCH, measured rather than assumed.
    `bf536372a5d` removed a helper that `field_hook_naming` and
    `field_hook_purity` still called; both died with `AttributeError: module
    'naming_vocabulary' has no attribute '_display'` on any real tree, and
    neither had a test. Re-introducing that break and re-running this sweep:
    **55 passed**. It does not catch it, because the empty-tree guard raises
    first and never reaches the broken line — a gate can be wholly unable to run
    and still refuse an empty tree correctly.

    So this is a tripwire for a gate that crashes on ITS OWN startup or scan
    setup, not a substitute for a test of the gate. What did catch that one was
    writing `test_field_hook_naming`; what would have caught it in CI is the
    ratchet step, which runs the gate over the real tree.
    """
    assert done.returncode != 0, (
        f"{gate} exited 0 on {what}; a gate that finds no inputs must refuse, "
        f"not report success.\n{done.stdout}{done.stderr}"
    )
    if gate in CRASHES_INSTEAD_OF_REFUSING:
        return
    assert "Traceback (most recent call last)" not in done.stderr, (
        f"{gate} CRASHED on {what} rather than refusing. The exit code is the "
        f"same, so this sweep would otherwise call it a pass — and a gate that "
        f"cannot run reports no findings at all.\n{done.stderr}"
    )


@pytest.mark.parametrize("gate", sorted(GATES))
def test_gate_refuses_a_present_but_empty_tree(gate, tmp_path):
    _assert_refuses(gate, _run(_checkout(tmp_path), gate), "a present-but-empty tree")


@pytest.mark.parametrize("gate", sorted(GATES))
def test_gate_refuses_a_tree_holding_only_non_source(gate, tmp_path):
    _assert_refuses(
        gate, _run(_checkout(tmp_path, litter=True), gate), "a tree holding no source"
    )


def test_the_crashing_list_shrinks_and_never_grows(tmp_path):
    """Both directions, so a gate cannot quietly join the list or stay on it.

    A gate that starts crashing is a regression; one that stops should be
    removed, or the pin implies a defect that is no longer there.
    """
    still_crashing = set()
    for gate in sorted(CRASHES_INSTEAD_OF_REFUSING):
        done = _run(_checkout(tmp_path / gate), gate)
        if "Traceback (most recent call last)" in done.stderr:
            still_crashing.add(gate)
    fixed = CRASHES_INSTEAD_OF_REFUSING - still_crashing
    assert not fixed, (
        f"{sorted(fixed)} now refuse properly. Remove them from "
        f"CRASHES_INSTEAD_OF_REFUSING so the debt cannot drift back up."
    )


def test_the_crashing_list_names_only_real_gates():
    ghosts = CRASHES_INSTEAD_OF_REFUSING - set(GATES)
    assert not ghosts, (
        f"{sorted(ghosts)} are pinned as crashers but are not swept gates. "
        f"Remove them."
    )

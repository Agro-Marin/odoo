import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent

GATES = {
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
    "py_function_length": ["--count"],
    "js_service_shape": ["--count"],
    "naming_vocabulary": ["--count"],
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
    "py_cycle_check": ["--check"],
    "package_index_check": ["--check"],
    "subsystem_map_check": ["--check"],
    "doc_restated_counts": ["--check"],
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


@pytest.mark.parametrize("gate", sorted(GATES))
def test_gate_refuses_a_present_but_empty_tree(gate, tmp_path):
    done = _run(_checkout(tmp_path), gate)
    assert done.returncode != 0, (
        f"{gate} exited 0 on a present-but-empty tree; a gate that finds no "
        f"inputs must refuse, not report success.\n{done.stdout}{done.stderr}"
    )


@pytest.mark.parametrize("gate", sorted(GATES))
def test_gate_refuses_a_tree_holding_only_non_source(gate, tmp_path):
    done = _run(_checkout(tmp_path, litter=True), gate)
    assert done.returncode != 0, (
        f"{gate} exited 0 on a tree holding no JS.\n{done.stdout}{done.stderr}"
    )

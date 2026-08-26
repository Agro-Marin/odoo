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
    "order_line_qty": ["--count"],
    "translation_catalog": ["--count"],
    "compute_context_deps": ["--count"],
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
    shutil.copytree(
        HERE,
        tmp_path / "tooling" / "architecture",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
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

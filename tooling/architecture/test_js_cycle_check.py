"""Tests for the JS import-cycle checker.

Stdlib + pytest only — no Odoo imports — so this runs in the same
database-free way as the checker itself. Run with:

    pytest tooling/architecture/test_js_cycle_check.py
"""

import js_cycle_check as jcc  # sys.path set by conftest.py

# --- SCC detection: synthetic graphs, no filesystem ---


def _cycles(graph):
    return sorted(tuple(c.modules) for c in jcc.find_cycles(graph))


def test_a_dag_has_no_cycles():
    graph = {"a": ["b", "c"], "b": ["c"], "c": ["d"], "d": []}
    assert _cycles(graph) == []


def test_a_two_module_cycle_is_found():
    graph = {"a": ["b"], "b": ["a"], "c": ["a"]}
    assert _cycles(graph) == [("a", "b")]


def test_the_py_js_shape_is_found_as_one_component():
    # The real six-module component this gate was written for: py_date reaches
    # py_builtin through py_args, and py_builtin reaches py_date back.
    graph = {
        "py_args": ["py_builtin"],
        "py_builtin": ["py_compare", "py_date", "py_utils"],
        "py_compare": ["py_builtin", "py_date"],
        "py_date": ["py_args", "py_timedelta"],
        "py_timedelta": ["py_args"],
        "py_utils": ["py_date"],
        "py_parser": [],
    }
    assert _cycles(graph) == [
        ("py_args", "py_builtin", "py_compare", "py_date", "py_timedelta", "py_utils")
    ]


def test_breaking_the_back_edge_removes_the_cycle():
    # What the fix did: py_args stopped importing py_builtin (EvaluationError
    # moved to a leaf), which drops py_date/py_timedelta/py_utils out of the
    # component and leaves a DAG.
    graph = {
        "py_args": ["py_errors"],
        "py_builtin": ["py_date", "py_utils", "py_type_name"],
        "py_compare": ["py_date", "py_errors", "py_type_name"],
        "py_date": ["py_args", "py_timedelta"],
        "py_timedelta": ["py_args"],
        "py_utils": ["py_date"],
        "py_type_name": ["py_date", "py_utils"],
        "py_errors": [],
    }
    assert _cycles(graph) == []


def test_a_self_import_counts_as_a_cycle():
    assert _cycles({"a": ["a"]}) == [("a",)]


def test_two_independent_cycles_are_reported_separately():
    graph = {"a": ["b"], "b": ["a"], "x": ["y"], "y": ["x"]}
    assert _cycles(graph) == [("a", "b"), ("x", "y")]


def test_edges_are_restricted_to_the_component():
    graph = {"a": ["b", "outside"], "b": ["a"], "outside": []}
    (cycle,) = jcc.find_cycles(graph)
    assert cycle.edges == [("a", "b"), ("b", "a")]


def test_dangling_targets_are_ignored():
    # An import of a module that is not in the graph (another addon, a lib)
    # must not crash or invent an edge.
    assert _cycles({"a": ["not_scanned"], "b": []}) == []


# --- specifier resolution ---


def test_relative_specifier_resolves_within_the_addon():
    assert (
        jcc._resolve("./py_date.js", "web/core/py_js/py_builtin")
        == "web/core/py_js/py_date"
    )


def test_relative_specifier_without_extension_resolves():
    assert (
        jcc._resolve("./py_date", "web/core/py_js/py_builtin")
        == "web/core/py_js/py_date"
    )


def test_parent_relative_specifier_resolves():
    assert (
        jcc._resolve("../registry.js", "web/core/py_js/py_builtin")
        == "web/core/registry"
    )


def test_addon_alias_resolves():
    assert (
        jcc._resolve("@web/core/registry", "web/views/list/list_view")
        == "web/core/registry"
    )


def test_a_cross_addon_import_resolves_to_the_other_addon():
    # The whole point of widening past `web`: an edge from mail into web is a
    # real edge, and so is one from mail into mail.
    assert (
        jcc._resolve("@web/core/registry", "mail/core/common/store_service")
        == "web/core/registry"
    )


def test_specifier_escaping_the_src_root_is_not_first_party():
    # `@web/../lib/...` and `@web/../tests/...` leave static/src entirely.
    assert jcc._resolve("@web/../lib/hoot/hoot", "web/core/domain") is None


def test_bare_and_external_specifiers_are_ignored():
    assert jcc._resolve("@odoo/owl", "web/core/domain") is None
    assert jcc._resolve("luxon", "web/core/l10n/luxon") is None


def test_specifier_to_a_nonexistent_addon_is_ignored():
    assert jcc._resolve("@no_such_addon/thing", "web/core/domain") is None


def test_specifier_to_a_nonexistent_file_is_ignored():
    assert jcc._resolve("@web/core/does_not_exist", "web/core/domain") is None


def test_every_addon_with_client_source_is_scanned():
    dirs = jcc.addon_src_dirs()
    assert "web" in dirs and "mail" in dirs
    assert dirs["web"].name == "src" and dirs["web"].parent.name == "static"


# --- the drift-zero contract itself, against the real tree ---


def test_no_new_cycles_in_the_web_addon():
    new, _known = jcc.check()
    assert new == [], "new JS import cycle(s): " + "; ".join(
        " <-> ".join(c.modules) for c in new
    )


def test_every_known_cycle_still_exists():
    # A pinned cycle that has since been broken is stale debt: drop the entry
    # so the gate keeps meaning what it says.
    _new, known = jcc.check()
    found = {frozenset(c.modules) for c in known}
    for entry in jcc.KNOWN_CYCLES:
        assert entry.modules in found, f"KNOWN_CYCLES entry is stale: {entry.modules}"


def test_known_cycles_carry_a_reason():
    for entry in jcc.KNOWN_CYCLES:
        assert entry.reason.strip(), f"{entry.modules} is pinned without a rationale"


def test_the_gate_refuses_a_tree_it_cannot_find(tmp_path, monkeypatch):
    # See test_layer_check for why every gate now proves it found its inputs.
    import pytest

    monkeypatch.setattr(jcc, "iter_source_files", list)
    with pytest.raises(SystemExit) as exc:
        jcc.main(["--check"])
    assert exc.value.code == 2

"""Tests for the JS Feature-Sliced layering checker.

Stdlib + pytest only — no Odoo imports — so this runs in the same
database-free way as the checker itself. Run with:

    pytest tooling/architecture/test_js_layer_check.py
"""

import js_layer_check as jlc  # sys.path set by conftest.py

# --- prefix matching is boundary-aware, never substring ---


def test_matches_spec_is_prefix_boundary_not_substring():
    assert jlc._matches_spec("@web/fields/x", ("@web/fields",))
    assert jlc._matches_spec("@web/fields", ("@web/fields",))
    # must not match a sibling that merely shares a string prefix
    assert not jlc._matches_spec("@web/fields_extra/x", ("@web/fields",))
    assert not jlc._matches_spec("@web/core/x", ("@web/fields",))


def test_matches_path_is_prefix_boundary_not_substring():
    assert jlc._matches_path("core/utils/x.js", ("core",))
    assert not jlc._matches_path("core_legacy/x.js", ("core",))
    assert jlc._matches_path("core/domain.js", ("core/domain.js",))


# --- the gap-closing contract is present and correctly shaped ---


def test_entity_below_feature_contract_exists():
    c = next(c for c in jlc.CONTRACTS if c.name == "entity-below-feature")
    assert c.source == ("model",)
    assert "@web/fields" in c.forbidden


def test_the_whole_layer_order_is_covered_by_some_contract():
    # The order is core < ui < components < model < fields < search < views <
    # webclient. A contract set that names only SOME of those steps reports
    # green while the unnamed ones drift, which is what the single flat
    # `shared` tier did: `services/` grew inside it for months, importing
    # freely across core/ui/components, and no contract could see it.
    order = [
        "core",
        "ui",
        "components",
        "model",
        "fields",
        "search",
        "views",
        "webclient",
    ]
    forbidden_by = {
        src: {f for c in jlc.CONTRACTS for f in c.forbidden if src in c.source}
        for src in order
    }
    missing = [
        (lower, higher)
        for i, lower in enumerate(order)
        for higher in order[i + 1 :]
        if f"@web/{higher}" not in forbidden_by[lower]
    ]
    assert missing == [], f"layer steps no contract forbids: {missing}"


def test_a_violation_of_each_new_contract_would_be_caught():
    # Guards the failure mode a green report cannot distinguish from a real
    # one: a contract whose source prefix matches no file, or whose forbidden
    # specifier is misspelt, passes silently forever.
    for name, module, spec in (
        ("core-below-ui-components", "core/x.js", "@web/ui/dialog/dialog"),
        ("ui-below-components", "ui/x.js", "@web/components/dropdown/dropdown"),
        (
            "components-below-entity",
            "components/x.js",
            "@web/model/relational_model/record",
        ),
        ("widget-order", "search/x.js", "@web/views/form/form_view"),
        ("widget-below-page", "views/x.js", "@web/webclient/webclient"),
    ):
        c = next(c for c in jlc.CONTRACTS if c.name == name)
        assert jlc._matches_path(module, c.source), name
        assert jlc._matches_spec(spec, c.forbidden), name


# --- regression guard: the real web tree is clean at zero ---


def test_real_tree_has_zero_new_violations():
    # This is the live invariant the CI --check enforces. If a refactor
    # reintroduces an upward import (e.g. a shared/ file importing @web/fields),
    # this fails here too, not only in CI.
    new, _known = jlc.check()
    assert new == [], "\n".join(
        f"{v.path}:{v.lineno}  {v.module} -> {v.imports} ({v.contract})" for v in new
    )


def test_the_gate_refuses_a_tree_it_cannot_find(tmp_path, monkeypatch):
    # See test_layer_check for why every gate now proves it found its inputs.
    import pytest

    monkeypatch.setattr(jlc, "WEB_SRC", tmp_path / "nothing")
    with pytest.raises(SystemExit) as exc:
        jlc.main(["--check"])
    assert exc.value.code == 2

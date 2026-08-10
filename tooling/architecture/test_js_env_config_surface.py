"""Tests for the ``env.config`` declared-shape gate.

Three of these exist because the first draft of the gate got them wrong, and
each wrong answer was the *confident* kind — a clean-looking run reporting keys
that do not exist, or a blind spot reported as a hazard.
"""

from pathlib import Path

import js_env_config_surface as gate
import pytest
from _repo_root import find_odoo_root


class TestRootResolution:
    def test_repo_root_is_the_checkout_root(self):
        assert (gate.ROOT / "odoo-bin").is_file()

    def test_missing_marker_raises_instead_of_guessing_a_root(self):
        with pytest.raises(SystemExit) as excinfo:
            find_odoo_root(Path("/nonexistent/deep/path"), tool="probe")
        assert "odoo-bin" in str(excinfo.value)

    def test_the_contract_file_exists_where_the_gate_expects_it(self):
        assert gate.CONTRACT.is_file(), gate.CONTRACT


class TestDeclaredSurface:
    def test_both_arrays_are_read(self):
        owned, foreign = gate.declared_surface()
        assert len(owned) > 20
        assert foreign

    def test_the_two_arrays_are_disjoint(self):
        owned, foreign = gate.declared_surface()
        assert not (owned & foreign)

    def test_a_missing_array_is_an_error_not_an_empty_set(self, monkeypatch, tmp_path):
        """An empty surface would declare every key undeclared, or none."""
        stub = tmp_path / "view_config.js"
        stub.write_text("export const SOMETHING_ELSE = [];\n")
        monkeypatch.setattr(gate, "CONTRACT", stub)
        with pytest.raises(SystemExit):
            gate.declared_surface()


class TestKeyExtraction:
    def test_a_plain_read_is_found(self):
        keys, ok = gate.keys_in("this.env.config.viewId")
        assert keys == {"viewId"} and ok

    def test_an_optional_chained_read_is_found(self):
        """`env.config?.actionName` is the only site reaching that key."""
        keys, _ = gate.keys_in("env.config?.actionName")
        assert keys == {"actionName"}

    def test_an_anchored_destructure_is_found(self):
        keys, _ = gate.keys_in("const { viewType, actionId } = this.env.config;")
        assert keys == {"viewType", "actionId"}

    def test_a_destructure_of_a_nested_value_is_not_a_config_destructure(self):
        """THE regression: the unanchored pattern invented two snake_case keys.

        `{ parent_res_model, parent_action_id } = env.config.embeddedActions[0]`
        destructures an embedded action, not the bag.
        """
        keys, _ = gate.keys_in(
            "const { parent_res_model, parent_action_id } = env.config.embeddedActions[0];"
        )
        assert keys == {"embeddedActions"}

    def test_an_alias_is_followed(self):
        source = "const config = this.env.config;\nif (config.viewType === 'form') {}"
        keys, ok = gate.keys_in(source)
        assert ok and {"viewType"} <= keys

    def test_an_honest_alias_is_not_reported_as_rebound(self):
        """THE regression: `\\s*=\\s*` matches zero-width, so a negative lookahead
        after it lands on whitespace and reports every alias as rebound."""
        _, ok = gate.keys_in("const config = this.env.config;\nconfig.viewId;")
        assert ok, "the tree's two honest alias sites were both flagged by this bug"

    def test_a_genuinely_rebound_alias_is_refused(self):
        source = (
            "const config = this.env.config;\n"
            "config.viewId;\n"
            "const config = this.model.config;\n"
        )
        _, ok = gate.keys_in(source)
        assert not ok, "`config` is reused fork-wide; an unchecked harvest invents keys"


class TestScope:
    def test_the_contract_file_is_not_its_own_consumer(self):
        """Its prose names `env.config.onNodeClicked` while explaining who sets it."""
        assert gate.CONTRACT not in set(gate._js_files(gate.ROOT))

    def test_tests_are_not_production_reach(self):
        scanned = list(gate._js_files(gate.WEB))
        assert scanned, "scanned nothing"
        assert not [p for p in scanned if "tests" in p.parts]

    def test_the_scan_finds_a_nonzero_number_of_keys(self):
        provenance, _ = gate.measure()
        assert provenance, "measured zero keys — the gate would pass against any tree"

    def test_an_empty_measurement_refuses_to_pass(self, monkeypatch):
        monkeypatch.setattr(gate, "measure", lambda *a, **k: ({}, 0))
        assert gate.main([]) == 2


class TestLiveTree:
    def test_every_reached_key_is_declared(self):
        owned, foreign = gate.declared_surface()
        provenance, _ = gate.measure()
        missing = gate.undeclared(provenance, owned, foreign)
        assert not missing, missing

    def test_no_file_is_unanalysable(self):
        _, unanalysable = gate.measure()
        assert unanalysable == gate.UNANALYSABLE_BUDGET

    def test_the_pin_matches_the_tree_for_present_scopes(self):
        provenance, _ = gate.measure()
        present = ["web", *[name for name, _ in gate._named_roots()]]
        new, gone = gate.drift(provenance, gate.read_pinned(), present)
        assert not new and not gone, (new, gone)

    def test_the_pin_is_not_empty(self):
        assert len(gate.read_pinned()) > 15

    def test_the_foreign_keys_are_still_foreign(self):
        """If web starts setting one, it should be promoted, not left here."""
        _, foreign = gate.declared_surface()
        provenance, _ = gate.measure()
        for key in foreign:
            assert "web" not in provenance.get(key, set()), (
                f"web now reaches `{key}` — promote it into VIEW_CONFIG_SURFACE"
            )


class TestDriftDirection:
    def test_a_new_reach_fails(self):
        pinned = {"viewId": frozenset({"web"})}
        new, gone = gate.drift(
            {"viewId": {"web"}, "invented": {"web"}}, pinned, ["web"]
        )
        assert new == {"web": ["invented"]} and not gone

    def test_surface_given_up_also_fails(self):
        pinned = {"viewId": frozenset({"web"}), "dropped": frozenset({"web"})}
        new, gone = gate.drift({"viewId": {"web"}}, pinned, ["web"])
        assert gone == {"web": ["dropped"]} and not new

    def test_an_absent_scope_is_not_judged(self):
        pinned = {"viewId": frozenset({"web", "enterprise"})}
        new, gone = gate.drift({"viewId": {"web"}}, pinned, ["web"])
        assert not new and not gone

from __future__ import annotations

import functools
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import payment_vocabulary as gate


@functools.cache
def _live_models():
    return gate.declared_models()


class TestTheNameRule:
    @pytest.mark.parametrize(
        "model", ["payment.transaction", "account.payment", "a.payment.b"]
    )
    def test_payment_as_a_dotted_component_is_caught(self, model):
        assert gate.carries_payment(model)

    @pytest.mark.parametrize("model", ["account.paymentish", "prepayment.line"])
    def test_payment_inside_a_component_is_not(self, model):
        assert not gate.carries_payment(model), (
            f"{model!r} does not carry 'payment' as a component; matching a "
            f"substring would flag every 'prepayment' in the tree"
        )

    @pytest.mark.parametrize("model", ["l10n_mx.payment", "l10n_it_edi.payment"])
    def test_a_localisation_model_is_recognised(self, model):
        assert gate.is_localisation(model)

    def test_a_core_model_is_not_a_localisation(self):
        assert not gate.is_localisation("payment.transaction")


class TestCategories:
    def test_the_category_is_read_before_the_double_dash(self):
        assert gate.category_of("method -- because it is one") == "method"
        assert gate.category_of("  channel  ") == "channel"

    def test_every_pinned_entry_names_a_real_category(self):
        bad = gate.miscategorised()
        assert bad == {}, (
            f"{sorted(bad)} carry an annotation whose category is not one of "
            f"{gate.CATEGORIES}"
        )

    def test_a_made_up_category_is_reported(self, monkeypatch):
        monkeypatch.setattr(gate, "load_allowlist", lambda: {"x.payment": "invented"})
        assert gate.miscategorised() == {"x.payment": "invented"}


class TestDeclaredModels:
    def _tree(self, tmp_path, monkeypatch, source: str):
        root = tmp_path / "addons"
        (root / "probe" / "models").mkdir(parents=True)
        (root / "probe" / "models" / "m.py").write_text(source, encoding="utf-8")
        monkeypatch.setattr(gate, "scan_roots", lambda: [root])
        return gate.declared_models()

    def test_a_declared_payment_model_is_found_with_its_description(
        self, tmp_path, monkeypatch
    ):
        found = self._tree(
            tmp_path,
            monkeypatch,
            "class P(models.Model):\n"
            '    _name = "payment.thing"\n'
            '    _description = "A Thing"\n',
        )
        assert "payment.thing" in found
        assert found["payment.thing"][0] == "A Thing"

    def test_an_extension_of_an_existing_model_is_not_a_declaration(
        self, tmp_path, monkeypatch
    ):
        found = self._tree(
            tmp_path,
            monkeypatch,
            "class P(models.Model):\n"
            '    _name = "payment.thing"\n'
            '    _inherit = ["payment.thing"]\n',
        )
        assert found == {}

    def test_a_model_without_payment_in_its_name_is_ignored(
        self, tmp_path, monkeypatch
    ):
        found = self._tree(
            tmp_path, monkeypatch, 'class P(models.Model):\n    _name = "sale.order"\n'
        )
        assert found == {}

    def test_tests_directories_are_not_scanned(self, tmp_path, monkeypatch):
        root = tmp_path / "addons"
        (root / "probe" / "tests").mkdir(parents=True)
        (root / "probe" / "tests" / "m.py").write_text(
            'class P(models.Model):\n    _name = "payment.fixture"\n', encoding="utf-8"
        )
        monkeypatch.setattr(gate, "scan_roots", lambda: [root])
        assert gate.declared_models() == {}


class TestUnlisted:
    def test_an_unlisted_model_is_reported(self, monkeypatch):
        monkeypatch.setattr(gate, "load_allowlist", dict)
        assert gate.unlisted({"payment.thing": (None, "p")}) == ["payment.thing"]

    def test_a_listed_model_is_not(self, monkeypatch):
        monkeypatch.setattr(gate, "load_allowlist", lambda: {"payment.thing": "method"})
        assert gate.unlisted({"payment.thing": (None, "p")}) == []

    def test_a_localisation_model_needs_no_entry(self, monkeypatch):
        monkeypatch.setattr(gate, "load_allowlist", dict)
        assert gate.unlisted({"l10n_mx.payment": (None, "p")}) == []


class TestSharedDescriptions:
    def test_two_models_sharing_a_description_are_reported_together(self):
        models = {
            "a.payment": ("Payment", "p"),
            "b.payment": ("Payment", "p"),
            "c.payment": ("Other", "p"),
        }
        assert gate.shared_descriptions(models) == {
            "Payment": ["a.payment", "b.payment"]
        }

    def test_a_model_with_no_description_is_not_grouped(self):
        assert gate.shared_descriptions({"a.payment": (None, "p")}) == {}


class TestRefusals:
    def test_prune_refuses_outside_the_full_workspace(self, monkeypatch, capsys):
        monkeypatch.setattr(gate, "in_full_workspace", lambda root: False)
        assert gate._run_prune() == 1
        assert "refusing to prune" in capsys.readouterr().err


class TestTheAllowlistFile:
    def test_it_parses_and_every_entry_states_a_category(self):
        allowed = gate.load_allowlist()
        assert allowed, "the allowlist is empty; the gate would flag nothing"
        for name, annotation in allowed.items():
            assert annotation.strip(), f"{name} is listed with no category"

    def test_the_written_form_round_trips_and_sorts(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gate, "ALLOWLIST", tmp_path / "a.json")
        gate.save_allowlist({"b.payment": "method", "a.payment": "channel"})
        payload = json.loads((tmp_path / "a.json").read_text(encoding="utf-8"))
        assert list(payload["models"]) == ["a.payment", "b.payment"]
        assert payload["categories"] == list(gate.CATEGORIES)
        assert gate.load_allowlist() == {"a.payment": "channel", "b.payment": "method"}


class TestTheTreeItGuards:
    def test_the_scan_reaches_the_real_tree(self):
        assert len(_live_models()) > 10

    def test_no_entry_names_a_model_that_is_gone(self):
        if not gate.in_full_workspace(gate.ROOT):
            pytest.skip("repo-alone checkout: the sibling roots are not present")
        stale = sorted(set(gate.load_allowlist()) - set(_live_models()))
        assert not stale, (
            f"{stale} are pinned but no checkout declares them; run --prune "
            f"from the full workspace"
        )

    def test_the_repository_is_clean(self):
        bad = gate.unlisted(_live_models())
        assert bad == [], f"unlisted 'payment' models: {bad}"

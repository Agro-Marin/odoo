from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import edi_vocabulary as gate


class TestTheNameRule:
    @pytest.mark.parametrize(
        "name", ["account_edi", "edi_proxy", "l10n_mx_edi_stock", "a_edi_b"]
    )
    def test_edi_as_a_component_is_caught(self, name):
        assert gate.carries_edi(name)

    @pytest.mark.parametrize(
        "name", ["credit", "editor", "edifice", "medium", "account_edit"]
    )
    def test_edi_inside_a_word_is_not(self, name):
        assert not gate.carries_edi(name), (
            f"{name!r} does not carry 'edi' as a component -- matching on a "
            f"substring would flag every 'editor' and 'credit' in the tree"
        )


class TestOffenders:
    def _tree(self, tmp_path, monkeypatch, names, allowed=None):
        root = tmp_path / "addons"
        for name in names:
            (root / name).mkdir(parents=True)
            (root / name / "__manifest__.py").write_text("{}", encoding="utf-8")
        monkeypatch.setattr(gate, "scan_roots", lambda: [root])
        monkeypatch.setattr(gate, "load_allowlist", lambda: allowed or {})

    def test_an_unlisted_edi_module_is_an_offender(self, tmp_path, monkeypatch):
        self._tree(tmp_path, monkeypatch, ["account_edi", "sale"])
        assert gate.offenders() == ["account_edi"]

    def test_a_listed_module_is_not(self, tmp_path, monkeypatch):
        self._tree(
            tmp_path, monkeypatch, ["account_edi"], allowed={"account_edi": "why"}
        )
        assert gate.offenders() == []

    def test_l10n_is_exempt_by_rule_and_needs_no_entry(self, tmp_path, monkeypatch):
        self._tree(tmp_path, monkeypatch, ["l10n_mx_edi", "l10n_it_edi"])
        assert gate.offenders() == []

    def test_offenders_come_back_sorted(self, tmp_path, monkeypatch):
        self._tree(tmp_path, monkeypatch, ["z_edi", "a_edi", "m_edi"])
        assert gate.offenders() == ["a_edi", "m_edi", "z_edi"]


class TestRefusals:
    def test_an_empty_tree_refuses_rather_than_passing(
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.setattr(gate, "scan_roots", lambda: [tmp_path / "absent"])
        monkeypatch.setattr(sys, "argv", ["edi_vocabulary.py", "--check"])
        assert gate.main() == 1
        assert "must refuse" in capsys.readouterr().err

    def test_prune_refuses_outside_the_full_workspace(
        self, monkeypatch, tmp_path, capsys
    ):
        monkeypatch.setattr(gate, "in_workspace", lambda root: False)
        monkeypatch.setattr(sys, "argv", ["edi_vocabulary.py", "--prune"])
        assert gate.main() == 1
        assert "refusing to prune" in capsys.readouterr().err


class TestTheAllowlistFile:
    def test_it_parses_and_every_entry_states_a_category(self):
        allowed = gate.load_allowlist()
        assert allowed, "the allowlist is empty; the gate would flag nothing"
        for name, why in allowed.items():
            assert why.strip(), f"{name} is listed with no reason"

    def test_no_entry_names_a_module_that_is_gone(self):
        if not gate.in_workspace(gate.ROOT):
            pytest.skip("repo-alone checkout: the sibling roots are not present")
        stale = sorted(set(gate.load_allowlist()) - set(gate.module_names()))
        assert not stale, (
            f"{stale} are pinned but no checkout provides them; run --prune "
            f"from the full workspace"
        )

    def test_the_written_form_round_trips(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gate, "ALLOWLIST", tmp_path / "a.json")
        gate.save_allowlist({"b_edi": "two", "a_edi": "one"})
        payload = json.loads((tmp_path / "a.json").read_text(encoding="utf-8"))
        assert list(payload["modules"]) == ["a_edi", "b_edi"], "entries are sorted"
        assert payload["adr"] == gate.ADR
        assert gate.load_allowlist() == {"a_edi": "one", "b_edi": "two"}


class TestTheTreeItGuards:
    def test_the_scan_reaches_the_real_tree(self):
        assert len(gate.module_names()) > 100

    def test_the_repository_is_clean(self):
        bad = gate.offenders()
        assert bad == [], f"unlisted 'edi' modules: {bad}"

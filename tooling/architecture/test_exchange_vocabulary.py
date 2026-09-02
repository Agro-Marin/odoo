from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import exchange_vocabulary as gate

FIELD = """
from odoo import fields, models


class Thing(models.Model):
    _name = "thing"

    {name} = fields.Selection(
        selection=[{values}],
    )
"""


def _values(*names: str) -> str:
    return ", ".join(f'("{name}", "{name.title()}")' for name in names)


class TestFindings:
    def _tree(self, tmp_path, monkeypatch, module, filename, source, allowed=None):
        root = tmp_path / "addons"
        (root / module / "models").mkdir(parents=True)
        (root / module / "models" / filename).write_text(source, encoding="utf-8")
        monkeypatch.setattr(gate, "scan_roots", lambda: [root])
        monkeypatch.setattr(gate, "load_allowlist", lambda: allowed or {})
        return root

    def test_a_new_vocabulary_in_an_exchange_module_is_an_offender(
        self, tmp_path, monkeypatch
    ):
        self._tree(
            tmp_path,
            monkeypatch,
            "l10n_zz_edi",
            "account_move.py",
            FIELD.format(name="l10n_zz_edi_state", values=_values("to_send", "acked")),
        )
        offenders = gate.offenders()
        assert [finding.key for finding in offenders] == [
            "l10n_zz_edi.l10n_zz_edi_state"
        ]
        assert offenders[0].values == ("to_send", "acked")

    def test_the_canonical_vocabulary_is_not_an_offence(self, tmp_path, monkeypatch):
        self._tree(
            tmp_path,
            monkeypatch,
            "l10n_zz_edi",
            "account_move.py",
            FIELD.format(name="state", values=_values(*gate.CANONICAL)),
        )
        assert gate.offenders() == []

    def test_a_subset_of_the_canonical_vocabulary_is_not_an_offence(
        self, tmp_path, monkeypatch
    ):
        self._tree(
            tmp_path,
            monkeypatch,
            "l10n_zz_edi",
            "account_move.py",
            FIELD.format(name="state", values=_values("draft", "queued", "sent")),
        )
        assert gate.offenders() == []

    def test_a_listed_field_is_not_an_offence(self, tmp_path, monkeypatch):
        self._tree(
            tmp_path,
            monkeypatch,
            "l10n_zz_edi",
            "account_move.py",
            FIELD.format(name="l10n_zz_edi_state", values=_values("to_send", "acked")),
            allowed={"l10n_zz_edi.l10n_zz_edi_state": "why"},
        )
        assert gate.offenders() == []

    def test_a_module_that_talks_to_nobody_is_out_of_scope(self, tmp_path, monkeypatch):
        self._tree(
            tmp_path,
            monkeypatch,
            "sale",
            "sale_order.py",
            FIELD.format(name="state", values=_values("draft", "weird")),
        )
        assert gate.offenders() == []

    def test_a_field_not_named_state_is_out_of_scope(self, tmp_path, monkeypatch):
        self._tree(
            tmp_path,
            monkeypatch,
            "l10n_zz_edi",
            "account_move.py",
            FIELD.format(name="l10n_zz_edi_kind", values=_values("a", "b")),
        )
        assert gate.offenders() == []

    def test_a_token_in_the_filename_brings_the_file_into_scope(
        self, tmp_path, monkeypatch
    ):
        self._tree(
            tmp_path,
            monkeypatch,
            "documents",
            "myinvois_document.py",
            FIELD.format(name="state", values=_values("weird", "shapes")),
        )
        assert [finding.key for finding in gate.offenders()] == ["documents.state"]

    def test_tests_and_migrations_are_skipped(self, tmp_path, monkeypatch):
        root = tmp_path / "addons"
        for part in ("tests", "migrations"):
            (root / "l10n_zz_edi" / part).mkdir(parents=True)
            (root / "l10n_zz_edi" / part / "thing.py").write_text(
                FIELD.format(name="state", values=_values("odd", "shapes")),
                encoding="utf-8",
            )
        monkeypatch.setattr(gate, "scan_roots", lambda: [root])
        monkeypatch.setattr(gate, "load_allowlist", dict)
        assert gate.offenders() == []

    def test_unparseable_python_does_not_stop_the_scan(self, tmp_path, monkeypatch):
        root = self._tree(
            tmp_path,
            monkeypatch,
            "l10n_zz_edi",
            "account_move.py",
            FIELD.format(name="state", values=_values("to_send", "acked")),
        )
        (root / "l10n_zz_edi" / "models" / "broken_edi.py").write_text(
            "def (:", encoding="utf-8"
        )
        assert [finding.key for finding in gate.offenders()] == ["l10n_zz_edi.state"]

    def test_findings_come_back_sorted(self, tmp_path, monkeypatch):
        root = tmp_path / "addons"
        for module in ("z_edi", "a_edi", "m_edi"):
            (root / module / "models").mkdir(parents=True)
            (root / module / "models" / "thing.py").write_text(
                FIELD.format(name="state", values=_values("odd", "shapes")),
                encoding="utf-8",
            )
        monkeypatch.setattr(gate, "scan_roots", lambda: [root])
        monkeypatch.setattr(gate, "load_allowlist", dict)
        assert [finding.module for finding in gate.offenders()] == [
            "a_edi",
            "m_edi",
            "z_edi",
        ]


class TestRefusals:
    def test_an_empty_tree_refuses_rather_than_passing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gate, "scan_roots", lambda: [tmp_path / "nowhere"])
        monkeypatch.setattr(gate, "load_allowlist", dict)
        monkeypatch.setattr(sys, "argv", ["exchange_vocabulary.py", "--check"])
        assert gate.main() == 1

    def test_prune_outside_a_workspace_refuses(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gate, "in_full_workspace", lambda root: False)
        monkeypatch.setattr(sys, "argv", ["exchange_vocabulary.py", "--prune"])
        assert gate.main() == 1

    def test_there_is_no_update_flag(self):
        source = Path(gate.__file__).read_text(encoding="utf-8")
        assert 'add_argument("--update"' not in source, (
            "a flag that rewrote the allowlist to whatever the tree holds would "
            "let the next vocabulary in silently -- ADR-0048 settled this for "
            "edi_vocabulary and the argument transfers"
        )


class TestRealTree:
    def test_the_allowlist_covers_the_tree(self):
        assert gate.offenders() == [], (
            "a state selection in an exchange module is unlisted; port it onto "
            "exchange.transmission or add it to the allowlist with the reason"
        )

    def test_every_entry_carries_a_reason(self):
        blank = [key for key, why in gate.load_allowlist().items() if not why.strip()]
        assert not blank, f"allowlist entries with no reason: {blank}"

    def test_no_entry_is_dead(self):
        if not gate.in_full_workspace(gate.ROOT):
            pytest.skip("repo-alone checkout: the sibling roots are not present")
        present = {finding.key for finding in gate.findings()}
        dead = sorted(set(gate.load_allowlist()) - present)
        assert not dead, (
            f"allowlist entries naming nothing in the tree: {dead}. Run --prune."
        )


@pytest.mark.parametrize("flag", ["--check", "--count", "--list"])
def test_the_cli_exits_zero_on_the_real_tree(monkeypatch, flag):
    monkeypatch.setattr(sys, "argv", ["exchange_vocabulary.py", flag])
    assert gate.main() == 0

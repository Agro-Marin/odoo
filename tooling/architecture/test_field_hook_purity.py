from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import field_hook_purity as gate

MODEL = """
from odoo import api, fields, models


class Thing(models.Model):
    _name = "thing"

{body}
"""


def _measure(tmp_path: Path, body: str) -> list[gate.Violation]:
    root = tmp_path / "addons" / "probe" / "models"
    root.mkdir(parents=True, exist_ok=True)
    (root / "thing.py").write_text(MODEL.format(body=body), encoding="utf-8")
    return gate.measure([tmp_path / "addons"])


class TestWhatCounts:
    def test_a_hook_nobody_calls_is_not_a_violation(self, tmp_path):
        body = (
            "    name = fields.Char(compute='_compute_name')\n"
            "\n"
            "    def _compute_name(self):\n"
            "        self.name = 'x'\n"
        )
        assert _measure(tmp_path, body) == []

    def test_a_hook_called_from_outside_its_own_family_is_reported(self, tmp_path):
        body = (
            "    name = fields.Char(compute='_compute_name')\n"
            "\n"
            "    def _compute_name(self):\n"
            "        self.name = 'x'\n"
            "\n"
            "    def action_do(self):\n"
            "        self._compute_name()\n"
        )
        found = _measure(tmp_path, body)
        assert [(v.model, v.method, v.calls) for v in found] == [
            ("thing", "_compute_name", 1)
        ]

    def test_a_sibling_hook_on_the_same_field_may_call_it(self, tmp_path):
        body = (
            "    name = fields.Char(compute='_compute_name', inverse='_inverse_name')\n"
            "\n"
            "    def _compute_name(self):\n"
            "        self.name = 'x'\n"
            "\n"
            "    def _inverse_name(self):\n"
            "        self._compute_name()\n"
        )
        assert _measure(tmp_path, body) == []

    def test_a_lambda_only_hook_is_exempt(self, tmp_path):
        body = (
            "    name = fields.Char(default=lambda self: self._default_name())\n"
            "\n"
            "    def _default_name(self):\n"
            "        return 'x'\n"
            "\n"
            "    def action_do(self):\n"
            "        self._default_name()\n"
        )
        assert _measure(tmp_path, body) == []

    def test_a_plain_method_that_is_no_hook_is_not_measured(self, tmp_path):
        body = (
            "    def _helper(self):\n"
            "        return 1\n"
            "\n"
            "    def action_do(self):\n"
            "        self._helper()\n"
        )
        assert _measure(tmp_path, body) == []


class TestOrdering:
    def test_findings_come_back_most_called_first(self, tmp_path):
        body = (
            "    a = fields.Char(compute='_compute_a')\n"
            "    b = fields.Char(compute='_compute_b')\n"
            "\n"
            "    def _compute_a(self):\n"
            "        self.a = 'x'\n"
            "\n"
            "    def _compute_b(self):\n"
            "        self.b = 'x'\n"
            "\n"
            "    def action_do(self):\n"
            "        self._compute_a()\n"
            "        self._compute_b()\n"
            "        self._compute_b()\n"
        )
        found = _measure(tmp_path, body)
        assert [v.method for v in found] == ["_compute_b", "_compute_a"]
        assert [v.calls for v in found] == [2, 1]


class TestRefusals:
    def test_an_empty_scan_refuses_rather_than_reporting_zero(self, tmp_path):
        (tmp_path / "empty").mkdir()
        with pytest.raises(RuntimeError, match="empty scan"):
            gate.measure([tmp_path / "empty"])

    def test_a_file_that_does_not_parse_is_skipped(self, tmp_path):
        root = tmp_path / "addons" / "probe" / "models"
        root.mkdir(parents=True)
        (root / "broken.py").write_text("def (\n", encoding="utf-8")
        (root / "ok.py").write_text(MODEL.format(body="    pass\n"), encoding="utf-8")
        assert gate.measure([tmp_path / "addons"]) == []


class TestTheTreeItGuards:
    def test_the_real_scan_reaches_the_tree(self):
        assert len(gate.nv._python_files([gate.ROOT / "odoo"])) > 100

    def test_the_repository_measures_at_or_under_its_floor(self):
        import json

        floor = json.loads(
            (
                gate.ROOT / "tooling" / "ratchet" / "baselines" / "hookpurity.json"
            ).read_text(encoding="utf-8")
        )["count"]
        found = gate.measure()
        assert len(found) == floor, (
            f"{len(found)} against a floor of {floor}; move the floor in the "
            f"same change:\n" + "\n".join(str(v) for v in found[:10])
        )


class TestCli:
    def test_count_prints_a_bare_integer(self, capsys):
        assert gate.main(["--count"]) == 0
        assert capsys.readouterr().out.strip().isdigit()

    def test_json_is_machine_readable(self, capsys):
        import json

        assert gate.main(["--json"]) == 0
        assert isinstance(json.loads(capsys.readouterr().out), list)

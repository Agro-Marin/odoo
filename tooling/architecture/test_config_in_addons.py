from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config_in_addons as gate


def _measure(tmp_path: Path, source: str) -> list[gate.ConfigReference]:
    path = tmp_path / "addons" / "thing" / "models" / "thing.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return gate.measure(files=[path])


def _shapes(found: list[gate.ConfigReference]) -> list[str]:
    return [item.shape for item in found]


def test_a_subscript_through_the_direct_import_is_a_reference(tmp_path):
    found = _measure(
        tmp_path, 'from odoo.tools import config\nx = config["dev_mode"]\n'
    )
    assert _shapes(found) == ["config[...]"]
    assert found[0].line == 2


def test_the_config_module_import_counts_the_same(tmp_path):
    found = _measure(
        tmp_path, 'from odoo.tools.config import config\nx = config.get("a")\n'
    )
    assert _shapes(found) == ["config.get"]


def test_tools_dot_config_and_odoo_dot_tools_dot_config_are_references(tmp_path):
    found = _measure(
        tmp_path,
        "from odoo import tools\nimport odoo\n"
        'a = tools.config["a"]\nb = odoo.tools.config.filestore("db")\n',
    )
    assert _shapes(found) == ["config[...]", "config.filestore"]


def test_an_alias_is_followed(tmp_path):
    found = _measure(
        tmp_path, "from odoo.tools import config as cfg\nx = cfg.options\n"
    )
    assert _shapes(found) == ["config.options"]


def test_every_reach_counts_not_every_file(tmp_path):
    found = _measure(
        tmp_path,
        "from odoo.tools import config\n"
        'a = config["a"]\nb = config["b"]\n\n\ndef f():\n    return config.get("c"), config\n',
    )
    assert sorted(_shapes(found)) == [
        "config",
        "config.get",
        "config[...]",
        "config[...]",
    ]


def test_a_name_the_module_did_not_import_from_odoo_tools_is_not_odoos(tmp_path):
    found = _measure(
        tmp_path,
        'config = {"a": 1}\nx = config["a"]\n\n\nclass M:\n    def g(self):\n'
        '        return self.config["a"], self.env["ir.config_parameter"]\n',
    )
    assert found == []


def test_a_parameter_shadows_the_import_for_its_body(tmp_path):
    found = _measure(
        tmp_path,
        "from odoo.tools import config\n\n\ndef f(config):\n"
        '    return config["a"]\n\n\nx = config["b"]\n',
    )
    assert [(item.line, item.shape) for item in found] == [(8, "config[...]")]


def test_a_write_is_a_reach_too(tmp_path):
    found = _measure(tmp_path, 'from odoo.tools import config\nconfig["a"] = 1\n')
    assert _shapes(found) == ["config[...]"]


def test_test_files_are_out_of_scope(tmp_path):
    path = tmp_path / "addons" / "thing" / "tests" / "test_thing.py"
    path.parent.mkdir(parents=True)
    path.write_text(
        'from odoo.tools import config\nx = config["a"]\n', encoding="utf-8"
    )
    assert gate.iter_source_files(tmp_path) == []


def test_an_empty_tree_is_refused(tmp_path):
    (tmp_path / "addons").mkdir()
    (tmp_path / "odoo" / "addons").mkdir(parents=True)
    with pytest.raises(RuntimeError, match="found nothing"):
        gate.measure(src=tmp_path)


def test_the_real_tree_has_findings_and_a_summary():
    found = gate.measure()
    assert found, "no bundled addon reaches odoo.tools.config -- the scan is broken"
    summary = gate._summary(found)
    assert "by shape:" in summary
    assert "config[...]" in summary

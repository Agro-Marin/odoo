from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _ast_cache
import py_addon_imports as gate

HERE = Path(__file__).resolve().parent


def _addon(root: Path, name: str, *files: str) -> Path:
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "__manifest__.py").write_text("{'name': 'x'}\n", encoding="utf-8")
    for rel in files:
        target = directory / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("", encoding="utf-8")
    return directory


def _scan(tmp_path: Path, source: str) -> list[gate.Unresolved]:
    scan = tmp_path / "scan"
    scan.mkdir(exist_ok=True)
    (scan / "consumer.py").write_text(source, encoding="utf-8")
    return gate.find_unresolved([scan], [tmp_path / "addons"])


class TestResolution:
    def test_an_import_of_a_present_addon_resolves(self, tmp_path):
        _addon(tmp_path / "addons", "sale")
        assert _scan(tmp_path, "from odoo.addons.sale import models\n") == []

    def test_an_import_of_a_present_submodule_resolves(self, tmp_path):
        _addon(tmp_path / "addons", "sale", "models/order.py")
        assert _scan(tmp_path, "from odoo.addons.sale.models.order import X\n") == []

    def test_a_submodule_that_is_a_package_resolves(self, tmp_path):
        _addon(tmp_path / "addons", "sale", "models/__init__.py")
        assert _scan(tmp_path, "from odoo.addons.sale.models import X\n") == []

    def test_a_missing_submodule_of_a_present_addon_is_reported(self, tmp_path):
        _addon(tmp_path / "addons", "sale")
        found = _scan(tmp_path, "from odoo.addons.sale.models.gone import X\n")
        assert [u.module for u in found] == ["odoo.addons.sale.models.gone"]

    def test_an_addon_no_checkout_provides_is_not_reported(self, tmp_path):
        _addon(tmp_path / "addons", "sale")
        assert _scan(tmp_path, "from odoo.addons.web_studio import X\n") == []

    def test_a_bare_import_statement_is_read_too(self, tmp_path):
        _addon(tmp_path / "addons", "sale")
        found = _scan(tmp_path, "import odoo.addons.sale.absent\n")
        assert [u.module for u in found] == ["odoo.addons.sale.absent"]

    def test_a_relative_import_is_not_an_addon_import(self, tmp_path):
        _addon(tmp_path / "addons", "sale")
        assert _scan(tmp_path, "from . import models\n") == []

    def test_a_non_addon_import_is_ignored(self, tmp_path):
        _addon(tmp_path / "addons", "sale")
        assert _scan(tmp_path, "from odoo.orm.models import BaseModel\n") == []


class TestExemptions:
    def test_a_type_checking_import_is_skipped(self, tmp_path):
        _addon(tmp_path / "addons", "sale")
        source = (
            "from typing import TYPE_CHECKING\n"
            "if TYPE_CHECKING:\n"
            "    from odoo.addons.sale.models.gone import X\n"
        )
        assert _scan(tmp_path, source) == []

    def test_a_runtime_fixture_addon_is_exempt(self, tmp_path):
        _addon(tmp_path / "addons", "rd_leaf")
        assert _scan(tmp_path, "from odoo.addons.rd_leaf.absent import X\n") == []

    def test_a_runtime_assembled_prefix_is_exempt(self, tmp_path):
        _addon(tmp_path / "addons", "iot_drivers")
        source = "from odoo.addons.iot_drivers.iot_handlers.absent import X\n"
        assert _scan(tmp_path, source) == []


class TestScanning:
    @pytest.mark.parametrize("part", sorted(gate.EXCLUDED_PARTS))
    def test_an_excluded_directory_is_not_scanned(self, tmp_path, part):
        _addon(tmp_path / "addons", "sale")
        scan = tmp_path / "scan" / part
        scan.mkdir(parents=True)
        (scan / "x.py").write_text(
            "from odoo.addons.sale.gone import X\n", encoding="utf-8"
        )
        assert gate.find_unresolved([tmp_path / "scan"], [tmp_path / "addons"]) == []

    def test_a_file_that_does_not_parse_is_reported_not_skipped(self, tmp_path):
        _addon(tmp_path / "addons", "sale")
        with pytest.raises(_ast_cache.SourceUnreadable) as raised:
            _scan(tmp_path, "def (\n")
        assert ".py" in str(raised.value)

    def test_findings_are_sorted_by_file_then_module(self, tmp_path):
        _addon(tmp_path / "addons", "sale")
        scan = tmp_path / "scan"
        scan.mkdir()
        (scan / "b.py").write_text("from odoo.addons.sale.z import X\n", "utf-8")
        (scan / "a.py").write_text(
            "from odoo.addons.sale.z import X\nfrom odoo.addons.sale.y import Y\n",
            "utf-8",
        )
        found = gate.find_unresolved([scan], [tmp_path / "addons"])
        assert [(Path(u.file).name, u.module.rsplit(".", 1)[1]) for u in found] == [
            ("a.py", "y"),
            ("a.py", "z"),
            ("b.py", "z"),
        ]


class TestTheTreeItGuards:
    def test_the_real_scan_reaches_something(self):
        roots = gate.discover_addons_roots()
        assert roots, "no addons root discovered"
        assert len(gate._addon_dirs(roots)) > 100, (
            "the addon index found almost nothing"
        )

    def test_the_repository_resolves_every_addon_import_it_makes(self):
        found = gate.find_unresolved(
            [gate.ROOT / "odoo", gate.ROOT / "addons"], gate.discover_addons_roots()
        )
        assert found == [], "\n".join(str(u) for u in found)


class TestCli:
    def _tree(self, tmp_path, source="from odoo.addons.sale import models\n"):
        _addon(tmp_path / "addons", "sale")
        scan = tmp_path / "scan"
        scan.mkdir()
        (scan / "consumer.py").write_text(source, encoding="utf-8")
        return ["--addons-root", str(tmp_path / "addons"), str(scan)]

    def test_check_exits_zero_when_every_import_resolves(self, tmp_path):
        assert gate.main([*self._tree(tmp_path), "--check"]) == 0

    def test_check_exits_one_on_an_unresolvable_import(self, tmp_path):
        argv = self._tree(tmp_path, "from odoo.addons.sale.gone import X\n")
        assert gate.main([*argv, "--check"]) == 1

    def test_without_check_it_reports_and_exits_zero(self, tmp_path):
        argv = self._tree(tmp_path, "from odoo.addons.sale.gone import X\n")
        assert gate.main(argv) == 0

    def test_json_is_machine_readable(self, tmp_path, capsys):
        argv = self._tree(tmp_path, "from odoo.addons.sale.gone import X\n")
        assert gate.main([*argv, "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert [row["module"] for row in payload] == ["odoo.addons.sale.gone"]

    def test_list_roots_prints_what_it_would_scan(self, tmp_path, capsys):
        argv = self._tree(tmp_path)
        assert gate.main([*argv, "--list-roots"]) == 0
        assert str(tmp_path / "scan") in capsys.readouterr().out

    def test_a_root_holding_no_python_is_refused(self, tmp_path):
        _addon(tmp_path / "addons", "sale")
        empty = tmp_path / "empty"
        empty.mkdir()
        with pytest.raises(SystemExit):
            gate.main(
                ["--addons-root", str(tmp_path / "addons"), str(empty), "--check"]
            )

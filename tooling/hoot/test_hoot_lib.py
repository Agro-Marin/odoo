"""Tests for the hoot runner's path anchoring and suite resolution.

``hoot_lib`` used to locate the checkout by counting parent directories, which
is exactly what breaks silently when a script is moved — and it was moved.
"""

from pathlib import Path

import hoot_lib as H
import pytest


class TestRootResolution:
    def test_odoo_root_is_the_checkout_root(self):
        assert (H.ODOO_ROOT / "odoo-bin").is_file()
        assert H.ODOO_BIN.is_file()

    def test_this_script_lives_under_the_resolved_root(self):
        assert Path(H.__file__).resolve().is_relative_to(H.ODOO_ROOT)

    def test_missing_marker_raises_instead_of_guessing(self):
        with pytest.raises(SystemExit) as excinfo:
            H._find_odoo_root(Path("/nonexistent/deep/path"))
        assert "odoo-bin" in str(excinfo.value)

    def test_config_resolves_to_a_real_file(self):
        assert H.CONF.is_file()


class TestSuiteResolution:
    def test_web_suite_resolves_test_files(self):
        assert H.suite_test_files("@web/core"), "@web/core resolved to no test files"

    def test_resolved_test_files_exist(self):
        assert all(Path(p).exists() for p in H.suite_test_files("@web/core"))

    def test_unknown_suite_resolves_to_nothing(self):
        assert not H.suite_test_files("@web/definitely_not_a_suite_xyz")

    def test_addons_for_suites_maps_prefix_to_module(self):
        assert "web" in H.addons_for_suites(["@web/core"])


class TestShardWeights:
    def test_weights_file_lives_under_data(self):
        weights = Path(H.__file__).resolve().parent / "data" / "hoot_shard_weights.json"
        assert weights.is_file(), "hoot-shard's weights table did not survive the move"

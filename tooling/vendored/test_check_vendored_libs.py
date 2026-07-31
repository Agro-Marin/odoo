"""Tests for the vendored-library gate's anchoring and manifest contract."""

from pathlib import Path

import check_vendored_libs as gate
import pytest


class TestRootResolution:
    def test_odoo_root_is_the_checkout_root(self):
        assert (gate.ODOO_ROOT / "odoo-bin").is_file()

    def test_lib_dir_resolves_to_the_vendored_tree(self):
        assert gate.LIB_DIR.is_dir()
        assert gate.LIB_DIR == gate.ODOO_ROOT / "addons/web/static/lib"

    def test_missing_marker_raises_instead_of_guessing(self):
        with pytest.raises(SystemExit) as excinfo:
            gate._find_odoo_root(Path("/nonexistent/deep/path"))
        assert "odoo-bin" in str(excinfo.value)


class TestManifest:
    def test_manifest_sits_in_the_vendored_tree(self):
        assert gate.MANIFEST.is_file()

    def test_manifest_loads_and_is_nonempty(self):
        """An empty manifest would make --drift pass by checking nothing."""
        assert gate._load_manifest()

    def test_every_pinned_library_names_a_version(self):
        libs = gate._load_manifest()
        entries = {k: v for k, v in libs.items() if isinstance(v, dict)}
        assert entries
        assert all("version" in v for v in entries.values())

from pathlib import Path

import generate_service_types as gen
import pytest
from _repo_root import find_odoo_root


class TestRootResolution:
    def test_odoo_root_is_the_checkout_root(self):
        assert (gen.ODOO_ROOT / "odoo-bin").is_file()

    def test_web_src_root_resolves_without_a_workspace_prefix(self):
        assert gen.WEB_SRC_ROOT.is_dir()
        assert gen.WEB_SRC_ROOT == gen.ODOO_ROOT / "addons/web/static/src"

    def test_missing_marker_raises_instead_of_guessing(self):
        with pytest.raises(SystemExit):
            find_odoo_root(Path("/nonexistent/deep/path"), tool="probe")


class TestOutputPathsAreMachineIndependent:
    def test_rel_strips_the_checkout_root(self):
        assert gen._rel(gen.ODOO_ROOT / "addons/web/x.ts") == Path("addons/web/x.ts")

    def test_rel_never_returns_an_absolute_in_tree_path(self):
        assert not gen._rel(gen.DEFAULT_OUTPUT).is_absolute()

    def test_rel_passes_through_paths_outside_the_checkout(self):
        outside = Path("/somewhere/else/x.ts")
        assert gen._rel(outside) == outside


class TestDiscovery:
    def test_discovers_registrations(self):
        assert gen.discover(), "no service registrations found under web/static/src"

    def test_finds_a_known_core_service(self):
        keys = {r.key for r in gen.discover()}
        assert "orm" in keys

    def test_import_paths_are_web_specifiers(self):
        assert all(r.import_path.startswith("@web/") for r in gen.discover())

    def test_test_and_legacy_registrations_are_skipped(self):
        sources = [str(r.source_file) for r in gen.discover()]
        assert not [s for s in sources if "/tests/" in s or "/legacy/" in s]

import shutil
import tempfile
import unittest
from pathlib import Path

from odoo.modules.migration import (
    VERSION_RE,
    _convert_version,
    _is_upgrade_version_dir,
    _migration_applies,
    _resolve_addon_path,
    _scripts_by_version,
)
from odoo.modules.module import adapt_version
from odoo.release import major_version

BaseCase = unittest.TestCase


class TestConvertVersion(BaseCase):
    def test_special_marker_unchanged(self):
        self.assertEqual(_convert_version("0.0.0"), "0.0.0")

    def test_bare_module_version_gets_server_prefix(self):
        self.assertEqual(_convert_version("2.0"), f"{major_version}.2.0")
        self.assertEqual(_convert_version("1.2.3"), f"{major_version}.1.2.3")

    def test_version_already_carrying_server_is_left_intact(self):
        self.assertEqual(_convert_version("17.0.1.2"), "17.0.1.2")


class TestMigrationApplies(BaseCase):
    def test_full_version_runs_once_then_stops(self):
        target = f"{major_version}.2.1"
        self.assertTrue(_migration_applies(target, f"{major_version}.2.0", target))
        self.assertFalse(_migration_applies(target, target, target))

    def test_majorless_runs_when_module_subversion_advances(self):
        self.assertTrue(
            _migration_applies("2.1", f"{major_version}.2.0", f"{major_version}.2.1")
        )

    def test_majorless_not_replayed_on_server_major_bump(self):
        self.assertFalse(_migration_applies("2.0", "9.0.2.0", "10.0.2.0"))

    def test_majorless_runs_across_major_when_subversion_advances(self):
        self.assertTrue(_migration_applies("2.0", "9.0.1.0", "10.0.2.0"))

    def test_zero_marker_runs_iff_installed_below_target(self):
        self.assertTrue(
            _migration_applies("0.0.0", f"{major_version}.2.0", f"{major_version}.2.1")
        )
        self.assertFalse(
            _migration_applies("0.0.0", f"{major_version}.2.1", f"{major_version}.2.1")
        )

    def test_empty_installed_version_is_tolerated(self):
        self.assertTrue(_migration_applies("0.0.0", "", f"{major_version}.1.0"))


class TestVersionRegex(BaseCase):
    def test_plain_module_versions(self):
        self.assertTrue(VERSION_RE.match("1.0"))
        self.assertTrue(VERSION_RE.match("19.0.1.0"))
        self.assertTrue(VERSION_RE.match("0.0.0"))

    def test_saas_prefixes(self):
        self.assertTrue(VERSION_RE.match("saas~18.1.2.0"))
        self.assertTrue(VERSION_RE.match("saas~99.1.2.0"))

    def test_saas_major_at_or_above_100_now_matches(self):
        self.assertTrue(VERSION_RE.match("saas~100.1.2.0"))
        self.assertTrue(VERSION_RE.match("saas~2106.1.2.0"))

    def test_old_dotted_saas_format(self):
        self.assertTrue(VERSION_RE.match("8.saas~6.1.0"))

    def test_rejects_garbage_and_incomplete(self):
        self.assertIsNone(VERSION_RE.match("abc"))
        self.assertIsNone(VERSION_RE.match("saas~18.1"))


class TestUpgradeScriptDiscovery(BaseCase):
    def _tmpdir(self):
        d = tempfile.mkdtemp(prefix="odoo_test_upgrade_")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        return d

    def test_is_upgrade_version_dir_accepts_valid_version_folder(self):
        d = self._tmpdir()
        Path(d, "19.0.1.0").mkdir()
        self.assertTrue(_is_upgrade_version_dir(d, "19.0.1.0"))

    def test_is_upgrade_version_dir_rejects_tests_and_non_dirs(self):
        d = self._tmpdir()
        Path(d, "tests").mkdir()
        self.assertFalse(_is_upgrade_version_dir(d, "tests"))
        self.assertFalse(_is_upgrade_version_dir(d, "does_not_exist"))

    def test_scripts_by_version_collects_py_and_skips_non_version_entries(self):
        d = self._tmpdir()
        version_dir = Path(d, "19.0.1.0")
        version_dir.mkdir()
        (version_dir / "pre-a.py").write_text("def migrate(cr, version): pass\n")
        (version_dir / "README.txt").write_text("ignored")
        Path(d, "tests").mkdir()
        result = _scripts_by_version(d)
        self.assertIn("19.0.1.0", result)
        self.assertNotIn("tests", result)
        self.assertTrue(any(f.endswith("pre-a.py") for f in result["19.0.1.0"]))
        self.assertFalse(any(f.endswith("README.txt") for f in result["19.0.1.0"]))

    def test_scripts_by_version_empty_path_returns_empty(self):
        self.assertEqual(_scripts_by_version(""), {})

    def test_resolve_addon_path_missing_returns_empty(self):
        self.assertEqual(_resolve_addon_path("no/such/addon_xyz/migrations"), "")


class TestVersionAlreadyCarryingTheSeries(BaseCase):
    """A manifest version that already names the series must not gain a second one.

    `check_version` accepts `19.0` and `19.0.1` and installs the module, so both
    reach `migrate_module` as the upgrade target. Prefixing them again inflated
    the target past every script the module owns; a no-op `-u` then ran all of
    them, and ran them again on the next `-u`. Reproduced end to end before the
    fix with three probe addons differing only in version string.
    """

    def test_the_bare_series_is_left_intact(self):
        self.assertEqual(_convert_version(major_version), major_version)

    def test_a_prefixed_three_part_version_is_left_intact(self):
        self.assertEqual(_convert_version(f"{major_version}.1"), f"{major_version}.1")

    def test_an_unprefixed_three_part_version_still_gains_the_series(self):
        self.assertEqual(_convert_version("1.2.3"), f"{major_version}.1.2.3")

    def test_it_agrees_with_adapt_version_on_every_installable_shape(self):
        for version in ("1.0", "1.7", "2.0.3", major_version, f"{major_version}.1"):
            adapted = adapt_version(version)
            self.assertEqual(
                _convert_version(adapted),
                adapted,
                f"{version!r} adapts to {adapted!r}, which _convert_version must "
                f"then leave alone",
            )

    def test_no_script_applies_when_the_module_is_at_its_target(self):
        for version in (f"{major_version}.1.7", major_version, f"{major_version}.1"):
            for script in ("1.1", "2.0", "18.9"):
                self.assertFalse(
                    _migration_applies(script, version, version),
                    f"script {script} replayed for a module already at {version}",
                )

    def test_a_real_upgrade_still_runs_the_scripts_it_should(self):
        installed, target = f"{major_version}.1.0", f"{major_version}.2.0"
        self.assertTrue(_migration_applies("1.1", installed, target))
        self.assertTrue(_migration_applies("2.0", installed, target))
        self.assertFalse(_migration_applies("2.1", installed, target))
        self.assertTrue(_migration_applies("0.0.0", installed, target))

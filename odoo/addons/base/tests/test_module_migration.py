from odoo.modules.migration import (
    VERSION_RE,
    _convert_version,
    _migration_applies,
)
from odoo.release import major_version
from odoo.tests.common import BaseCase


class TestConvertVersion(BaseCase):
    def test_special_marker_unchanged(self):
        self.assertEqual(_convert_version("0.0.0"), "0.0.0")

    def test_bare_module_version_gets_server_prefix(self):
        self.assertEqual(_convert_version("2.0"), f"{major_version}.2.0")
        self.assertEqual(_convert_version("1.2.3"), f"{major_version}.1.2.3")

    def test_version_already_carrying_server_is_left_intact(self):
        # more than two dots => already prefixed with the server version
        self.assertEqual(_convert_version("17.0.1.2"), "17.0.1.2")


class TestMigrationApplies(BaseCase):
    """Behaviour of the version comparator extracted from MigrationManager.

    Cases are phrased against the running ``major_version`` where possible, and
    use literal cross-major versions for the documented majorless invariant so
    the test holds on any Odoo release.
    """

    def test_full_version_runs_once_then_stops(self):
        target = f"{major_version}.2.1"
        self.assertTrue(_migration_applies(target, f"{major_version}.2.0", target))
        # already at target => not strictly greater than installed => skip
        self.assertFalse(_migration_applies(target, target, target))

    def test_majorless_runs_when_module_subversion_advances(self):
        self.assertTrue(
            _migration_applies("2.1", f"{major_version}.2.0", f"{major_version}.2.1")
        )

    def test_majorless_not_replayed_on_server_major_bump(self):
        # The canonical case: a '2.0' script applied at 9.0 must NOT re-run when
        # the server bumps to 10.0 but the module sub-version is unchanged.
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
        # a freshly tracked module may have no recorded version
        self.assertTrue(_migration_applies("0.0.0", "", f"{major_version}.1.0"))


class TestVersionRegex(BaseCase):
    """VERSION_RE accepts full [server-prefix.]module-version strings only."""

    def test_plain_module_versions(self):
        self.assertTrue(VERSION_RE.match("1.0"))
        self.assertTrue(VERSION_RE.match("19.0.1.0"))
        self.assertTrue(VERSION_RE.match("0.0.0"))

    def test_saas_prefixes(self):
        self.assertTrue(VERSION_RE.match("saas~18.1.2.0"))
        self.assertTrue(VERSION_RE.match("saas~99.1.2.0"))

    def test_saas_major_at_or_above_100_now_matches(self):
        # Previously rejected (the year-2106 FIXME); the >=100 branch is fixed.
        self.assertTrue(VERSION_RE.match("saas~100.1.2.0"))
        self.assertTrue(VERSION_RE.match("saas~2106.1.2.0"))

    def test_old_dotted_saas_format(self):
        # x.saas~y form for x in 7..10
        self.assertTrue(VERSION_RE.match("8.saas~6.1.0"))

    def test_rejects_garbage_and_incomplete(self):
        self.assertIsNone(VERSION_RE.match("abc"))
        # a server prefix with no module version is not a complete version
        self.assertIsNone(VERSION_RE.match("saas~18.1"))

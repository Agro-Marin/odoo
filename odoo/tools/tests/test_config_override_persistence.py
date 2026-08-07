import unittest
from unittest.mock import patch

from odoo.tools.config import configmanager

# `config["x"] = y` used to land in the same ChainMap layer that
# `_postprocess_options()` starts by clearing, so every programmatic override
# silently evaporated on the next `parse_config()`. Four live writers depended
# on it working:
#
#   modules/db.py:245  config["load_language"] = lang
#   modules/db.py:294  config["load_language"] = saved_load_language   <- restore
#   cli/upgrade_code.py:282  config["addons_path"] = requested
#   cli/db.py:306  config["list_db"] = True
#
# The modules/db.py pair is the dangerous one: it saves a value, changes it, and
# restores it. If the clear happened in between, the *saved* value was lost too.
#
# Overrides now live in their own `_override_options` map, above the derived
# `_runtime_options` map that is cleared and recomputed. The invariant, which is
# what these tests pin: what a caller set explicitly survives re-parsing; what
# post-processing derived does not.


class TestOverridePersistence(unittest.TestCase):
    def setUp(self):
        patcher = patch.dict("os.environ", {}, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.config = configmanager()

    def test_explicit_override_survives_reparsing(self):
        default = self.config["db_maxconn"]
        self.config["db_maxconn"] = default + 935
        self.config.parse_config([], setup_logging=False)
        self.assertEqual(self.config["db_maxconn"], default + 935)

    def test_save_change_restore_round_trip_across_a_reparse(self):
        # The modules/db.py shape, which is what actually breaks.
        saved = self.config["load_language"]
        self.config["load_language"] = "fr_FR"
        self.config.parse_config([], setup_logging=False)
        self.assertEqual(self.config["load_language"], "fr_FR")
        self.config["load_language"] = saved
        self.assertEqual(self.config["load_language"], saved)

    def test_override_lands_in_its_own_map_not_the_derived_one(self):
        self.config["db_maxconn"] = 123
        self.assertIn("db_maxconn", self.config._override_options)
        self.assertNotIn("db_maxconn", self.config._runtime_options)

    def test_pop_removes_the_override_and_reveals_the_lower_layer(self):
        default = self.config["db_maxconn"]
        self.config["db_maxconn"] = default + 7
        self.assertEqual(self.config.pop("db_maxconn"), default + 7)
        self.assertEqual(self.config["db_maxconn"], default)

    def test_derived_values_are_still_recomputed_not_persisted(self):
        # The other half of the invariant: _postprocess_options() must keep
        # clearing what it derives, or a stale derivation would outlive its
        # inputs. `test_enable` is derived from `test_tags`.
        self.config.parse_config([], setup_logging=False)
        self.assertIn("test_enable", self.config._runtime_options)
        before = dict(self.config._runtime_options)
        self.config.parse_config([], setup_logging=False)
        self.assertEqual(dict(self.config._runtime_options), before)

    def test_override_outranks_the_command_line(self):
        # An explicit programmatic write is the most deliberate act available,
        # so it sits at the top of the ChainMap. Pinned because it is a real
        # precedence decision, not an accident of map order.
        self.config.parse_config(["--db_maxconn", "5"], setup_logging=False)
        self.assertEqual(self.config["db_maxconn"], 5)
        self.config["db_maxconn"] = 11
        self.config.parse_config(["--db_maxconn", "5"], setup_logging=False)
        self.assertEqual(self.config["db_maxconn"], 11)

    def test_sources_report_distinguishes_override_from_derived(self):
        self.config["db_maxconn"] = 321
        sources = self.config._get_sources("db_maxconn")
        self.assertEqual(sources["override"], 321)
        self.assertIn("runtime", sources)

    def test_deprecated_rcfile_setter_behaves_like_the_documented_form(self):
        # Its own DeprecationWarning says to use `config["config"] = ...`
        # instead, so it must land in the same place.
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            self.config.rcfile = "/tmp/some-odoorc"
        self.assertEqual(self.config._override_options["config"], "/tmp/some-odoorc")


if __name__ == "__main__":
    unittest.main()

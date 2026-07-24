"""Regression tests for ``odoo.libs.datetime.tz.timezone``."""

import unittest
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from odoo.libs.datetime.tz import timezone


class TestTimezone(unittest.TestCase):
    def test_valid_name(self):
        self.assertIsInstance(timezone("Europe/Paris"), ZoneInfo)

    def test_unknown_name_raises_zoneinfo_not_found(self):
        # documented contract (:raises ZoneInfoNotFoundError:); previously the
        # specific error was downgraded to a plain KeyError.
        with self.assertRaises(ZoneInfoNotFoundError):
            timezone("Not/AZone")

    def test_legacy_turkey_alias_resolves(self):
        # the legacy tzdata name is "Turkey" (not "Türkiye"); it must resolve on
        # systems whose trimmed tzdata drops the backward-compat links.
        self.assertIsInstance(timezone("Turkey"), ZoneInfo)


if __name__ == "__main__":
    unittest.main()

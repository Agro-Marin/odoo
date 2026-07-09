"""Regression tests for ``odoo.libs.filesystem.osutil.WINDOWS_RESERVED``.

The pattern uses ``(?:...)`` (non-capturing); the previous ``(:?...)`` was a
capturing group beginning with an optional colon, so ``":CON"`` matched.
"""

import unittest

from odoo.libs.filesystem.osutil import WINDOWS_RESERVED


class TestWindowsReserved(unittest.TestCase):
    def test_reserved_names_match(self):
        for name in ("CON", "PRN", "AUX", "NUL", "COM1", "LPT9", "nul", "CON.txt"):
            self.assertTrue(WINDOWS_RESERVED.match(name), name)

    def test_non_reserved_do_not_match(self):
        # ":CON" was a false positive; COM0/LPT0 are not reserved devices.
        for name in (":CON", "CONFIG", "COM0", "LPT0", "README"):
            self.assertFalse(WINDOWS_RESERVED.match(name), name)


if __name__ == "__main__":
    unittest.main()

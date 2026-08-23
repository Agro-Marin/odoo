import unittest

from odoo.modules.module import adapt_version, check_version
from odoo.release import major_version

BaseCase = unittest.TestCase


class TestCheckVersion(BaseCase):
    def test_should_raise_false_never_raises(self):
        self.assertFalse(check_version("garbage", should_raise=False))
        self.assertFalse(check_version("1.2.3.4.5.6", should_raise=False))

    def test_should_raise_true_raises_on_malformed(self):
        with self.assertRaises(ValueError):
            check_version("garbage")

    def test_verdicts(self):
        self.assertTrue(check_version(major_version, should_raise=False))
        self.assertTrue(check_version(f"{major_version}.1.0", should_raise=False))
        self.assertFalse(check_version("1.2.3.4", should_raise=False))


class TestAdaptVersion(BaseCase):
    def test_bare_versions_get_serie_prefix(self):
        self.assertEqual(adapt_version("1.0"), f"{major_version}.1.0")
        self.assertEqual(adapt_version("2.5"), f"{major_version}.2.5")
        self.assertEqual(adapt_version("1.2.3"), f"{major_version}.1.2.3")

    def test_serie_prefixed_versions_unchanged(self):
        self.assertEqual(adapt_version(major_version), major_version)
        self.assertEqual(adapt_version(f"{major_version}.1.2"), f"{major_version}.1.2")
        self.assertEqual(
            adapt_version(f"{major_version}.1.2.3"), f"{major_version}.1.2.3"
        )

    def test_four_part_non_serie_version_is_left_unchanged(self):
        self.assertEqual(adapt_version("1.2.3.4"), "1.2.3.4")

    def test_rejects_malformed(self):
        for bad in ("abc", "1", "1.2.3.4.5.6", "1.x"):
            with self.assertRaises(ValueError):
                adapt_version(bad)

import itertools
import unittest

from odoo.libs.parse_version import parse_version


class TestParseVersion(unittest.TestCase):
    def assert_increasing(self, versions: tuple[str, ...]) -> None:
        parsed = [parse_version(v) for v in versions]
        for (va, a), (vb, b) in itertools.pairwise(zip(versions, parsed, strict=True)):
            self.assertLess(
                a, b, f"expected parse_version({va!r}) < parse_version({vb!r})"
            )

    def test_release_series_ordering(self):
        self.assert_increasing(
            (
                "0",
                "4.2",
                "4.2.3.4",
                "5.0.0-alpha",
                "5.0.0-rc1",
                "5.0.0-rc1.1",
                "5.0.0_rc2",
                "5.0.0_rc3",
                "5.0.0",
            )
        )

    def test_patchlevel_ordering(self):
        self.assert_increasing(("5.0.0-0_rc3", "5.0.0-1dev", "5.0.0-1"))

    def test_trailing_zeros_are_equivalent(self):
        self.assertEqual(parse_version("2.4"), parse_version("2.4.0"))

    def test_empty_defaults_to_0_1(self):
        self.assertEqual(parse_version(""), parse_version("0.1"))

    def test_saas_prefix_is_dropped(self):
        self.assertEqual(parse_version("saas~19.0"), parse_version("19.0"))


if __name__ == "__main__":
    unittest.main()

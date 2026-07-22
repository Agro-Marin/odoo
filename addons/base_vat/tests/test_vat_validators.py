"""Tests for the country-specific VAT validators and dispatch."""

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestVatValidators(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Partner = cls.env["res.partner"]

    def test_split_vat_with_country_prefix(self):
        """A country prefix is split off the number part."""
        self.assertEqual(self.Partner._split_vat("BE0477472701"), ("BE", "0477472701"))

    def test_split_vat_without_prefix(self):
        """A number with no alpha prefix is returned whole (boundary)."""
        self.assertEqual(self.Partner._split_vat("0477472701"), ("", "0477472701"))

    def test_check_vat_mx_valid_rfc(self):
        """A well-formed Mexican RFC with a valid embedded date passes."""
        # AAA + 010101 (2001-01-01) + 3-char homoclave.
        self.assertTrue(self.Partner.check_vat_mx("AAA010101AAA"))

    def test_check_vat_mx_bad_date_rejected(self):
        """An RFC whose embedded date is impossible is rejected (negative)."""
        # month 13 does not exist.
        self.assertFalse(self.Partner.check_vat_mx("AAA011301AAA"))

    def test_check_vat_mx_bad_format_rejected(self):
        """An RFC that does not match the pattern is rejected (negative)."""
        self.assertFalse(self.Partner.check_vat_mx("not-an-rfc"))

    def test_check_vat_number_dispatches_to_country(self):
        """_check_vat_number routes to the country-specific validator."""
        self.assertTrue(self.Partner._check_vat_number("mx", "AAA010101AAA"))
        self.assertFalse(self.Partner._check_vat_number("mx", "AAA011301AAA"))

    def test_check_vat_number_unknown_country_passes(self):
        """A country with no validator and no stdnum module passes (boundary)."""
        self.assertTrue(self.Partner._check_vat_number("zz", "whatever"))

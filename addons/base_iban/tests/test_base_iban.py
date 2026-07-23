# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged

from odoo.addons.base_iban.models.res_partner_bank import (
    get_bban_from_iban,
    normalize_iban,
    pretty_iban,
    validate_iban,
)

# Canonical valid Belgian IBAN (Wikipedia example), 16 chars.
VALID_IBAN = "BE68539007547034"


@tagged("post_install", "-at_install")
class TestBaseIban(TransactionCase):
    """Tests for the IBAN helper functions and validation in base_iban."""

    def test_normalize_iban_strips_separators(self):
        """normalize_iban removes spaces and punctuation, keeping alphanumerics."""
        self.assertEqual(normalize_iban("BE68 5390-0754_7034"), VALID_IBAN)

    def test_pretty_iban_groups_valid_in_fours(self):
        """A valid IBAN is reformatted into space-separated groups of four."""
        self.assertEqual(pretty_iban(VALID_IBAN), "BE68 5390 0754 7034")

    def test_pretty_iban_leaves_invalid_untouched(self):
        """Boundary: an invalid IBAN is returned unchanged (no grouping)."""
        self.assertEqual(pretty_iban("XX"), "XX")

    def test_get_bban_from_iban_drops_country_and_check(self):
        """The BBAN is the IBAN without its leading country code and check digits."""
        self.assertEqual(get_bban_from_iban(VALID_IBAN), "539007547034")

    def test_validate_iban_accepts_valid(self):
        """validate_iban returns None (no error) for a well-formed IBAN."""
        self.assertIsNone(validate_iban(VALID_IBAN))

    def test_validate_iban_empty_raises(self):
        """An empty IBAN is rejected."""
        with self.assertRaises(ValidationError):
            validate_iban("")

    def test_validate_iban_unknown_country_raises(self):
        """An IBAN whose country code is not in the template map is rejected."""
        with self.assertRaises(ValidationError):
            validate_iban("ZZ68539007547034")

    def test_validate_iban_wrong_length_raises(self):
        """An IBAN of the wrong length for its country is rejected."""
        with self.assertRaises(ValidationError):
            validate_iban("BE123")

    def test_validate_iban_bad_check_digits_raises(self):
        """Tampering with the check digits fails the mod-97 validation."""
        with self.assertRaises(ValidationError):
            validate_iban("BE69539007547034")

    def test_check_iban_returns_bool(self):
        """res.partner.bank.check_iban returns True for valid, False for invalid."""
        Bank = self.env["res.partner.bank"]
        self.assertTrue(Bank.check_iban(VALID_IBAN))
        self.assertFalse(Bank.check_iban("not-an-iban"))

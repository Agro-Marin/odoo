"""Tests for the phone parsing/formatting helpers (phonenumbers-backed)."""

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.phone_validation.tools.phone_validation import (
    phone_format,
    phone_get_region_data_for_number,
)


@tagged("post_install", "-at_install")
class TestPhoneFormatTools(TransactionCase):
    def test_format_e164(self):
        """A national number formats to E164 with the country prefix."""
        self.assertEqual(
            phone_format("55 1234 5678", "MX", 52, force_format="E164"),
            "+525512345678",
        )

    def test_format_international(self):
        """International format keeps the + prefix and grouping."""
        formatted = phone_format("5512345678", "MX", 52, force_format="INTERNATIONAL")
        self.assertTrue(formatted.startswith("+52"))

    def test_double_zero_prefix_recovered(self):
        """Numbers entered as 00<code>... are recovered as +<code>..."""
        self.assertEqual(
            phone_format("00525512345678", "MX", 52, force_format="E164"),
            "+525512345678",
        )

    def test_too_short_number_rejected(self):
        """A number with too few digits raises a UserError (negative)."""
        with self.assertRaises(UserError):
            phone_format("12", "MX", 52)

    def test_invalid_number_returned_verbatim_without_exception(self):
        """raise_exception=False degrades to returning the input (boundary)."""
        self.assertEqual(phone_format("12", "MX", 52, raise_exception=False), "12")

    def test_region_data_for_international_number(self):
        """Region data extracts country code and national number."""
        data = phone_get_region_data_for_number("+525512345678")
        self.assertEqual(data["code"], "MX")
        self.assertEqual(data["phone_code"], "52")
        self.assertEqual(data["national_number"], "5512345678")

    def test_region_data_for_garbage_is_empty(self):
        """Unparseable input yields the empty region payload (boundary)."""
        data = phone_get_region_data_for_number("garbage")
        self.assertEqual(data, {"code": "", "national_number": "", "phone_code": ""})

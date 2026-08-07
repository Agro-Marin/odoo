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


@tagged("post_install", "-at_install")
class TestPhoneParseRecoveryBranches(TransactionCase):
    """TOO_LONG recovery ladder and invalid-prefix taxonomy of phone_parse."""

    def test_unparseable_plus_number_rejected(self):
        """A '+' number with an impossible country code fails at parse."""
        with self.assertRaises(UserError) as cm:
            phone_format("+9991234567890", "FR", 33)
        self.assertIn("Unable to parse", str(cm.exception))

    def test_no_plus_prefix_recovered(self):
        """'33612345678' (missing '+') is retried as '+33612345678'."""
        self.assertEqual(
            phone_format("33612345678", "FR", 33, force_format="E164"),
            "+33612345678",
        )

    def test_genuinely_too_long_rejected(self):
        """A number too long even after recovery names the right error."""
        with self.assertRaises(UserError) as cm:
            phone_format("0033612345678901234", "FR", 33)
        self.assertIn("too many digits", str(cm.exception))

    def test_patched_region_metadata_formats(self):
        """Regions carrying local metadata patches still format cleanly."""
        for number, country, code, expected in [
            ("11961234567", "BR", 55, "+5511961234567"),
            ("6017654321", "CO", 57, "+576017654321"),
            ("650123456", "MA", 212, "+212650123456"),
        ]:
            self.assertEqual(
                phone_format(number, country, code, force_format="E164"),
                expected,
            )


@tagged("post_install", "-at_install")
class TestPhoneBlacklistRemoveWizard(TransactionCase):
    """The unblacklist wizard delegates to phone.blacklist._remove."""

    def test_wizard_unblacklists_number_with_reason(self):
        Blacklist = self.env["phone.blacklist"]
        Blacklist._add(["+33612345678"])
        self.assertTrue(Blacklist.search([("number", "=", "+33612345678")]).active)

        wizard = self.env["phone.blacklist.remove"].create(
            {"phone": "+33612345678", "reason": "customer request"}
        )
        wizard.action_unblacklist_apply()

        self.assertFalse(Blacklist.search([("number", "=", "+33612345678")]).active)

    def test_wizard_invalid_number_raises(self):
        """The wizard rejects an unparseable phone number (negative)."""
        wizard = self.env["phone.blacklist.remove"].create(
            {"phone": "12", "reason": "test"}
        )

        with self.assertRaises(UserError):
            wizard.action_unblacklist_apply()

        self.assertFalse(self.env["phone.blacklist"].search([("number", "=", "12")]))

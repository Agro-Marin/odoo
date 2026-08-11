from odoo.tests import TransactionCase, tagged

from odoo.addons.phone_validation.tools.phone_validation import (
    phone_format,
    phone_get_country_code_for_number,
)


@tagged("post_install", "-at_install")
class TestPhoneFormatVariants(TransactionCase):
    """Output formats of ``phone_format`` beyond the international default.

    The existing suite pins E164, the international format and the recovery
    of numbers typed without a ``+``. What is left is the national format
    and the guard that decides when it may be used at all.
    """

    BE_LOCAL = "0485112233"
    FR_NUMBER = "+33485112233"

    def test_a_local_number_can_be_written_the_way_it_is_dialled(self):
        """In its own country a number is rendered in national form."""
        self.assertEqual(
            phone_format(self.BE_LOCAL, "BE", 32, force_format="NATIONAL"),
            "0485 11 22 33",
        )

    def test_a_foreign_number_is_never_written_as_a_local_one(self):
        """A number from elsewhere stays international even if asked otherwise.

        Rendering a French number in Belgian national form would produce a
        string nobody can dial, so the country mismatch overrides the
        requested format.
        """
        self.assertEqual(
            phone_format(self.FR_NUMBER, "BE", 32, force_format="NATIONAL"),
            "+33 4 85 11 22 33",
        )

    def test_a_number_can_be_written_as_a_dialling_link(self):
        """RFC3966 is the form a phone link in a page needs."""
        self.assertEqual(
            phone_format(self.BE_LOCAL, "BE", 32, force_format="RFC3966"),
            "tel:+32-485-11-22-33",
        )

    def test_the_country_of_a_number_is_read_from_the_number_itself(self):
        """The country comes from the prefix, not from any context passed in."""
        self.assertEqual(phone_get_country_code_for_number(self.FR_NUMBER), "FR")

    def test_a_number_that_names_no_country_reports_none(self):
        """Garbage yields an empty country rather than a guess (negative)."""
        self.assertEqual(phone_get_country_code_for_number("abc"), "")

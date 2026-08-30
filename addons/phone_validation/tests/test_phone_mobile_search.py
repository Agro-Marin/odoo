from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPhoneMobileSearch(TransactionCase):
    """``phone_mobile_search`` must match on the sanitized (E164) form too.

    A contact's raw ``phone``/``mobile`` field can be typed in any local
    format; ``phone_sanitized`` normalizes it. Without including
    ``phone_sanitized`` among the fields consulted by
    ``_search_phone_mobile_search``, searching by the normalized form misses
    a contact whose raw number is stored differently.
    """

    def test_search_by_sanitized_form_matches_a_locally_stored_number(self):
        partner = self.env["res.partner"].create(
            {
                "name": "Local-format contact",
                "phone": "012345678",
                "country_id": self.env.ref("base.be").id,
            }
        )
        self.assertEqual(partner.phone_sanitized, "+3212345678")
        # _search_phone_mobile_search runs raw SQL against the stored
        # columns, bypassing the ORM cache; flush so it sees this write.
        self.env.flush_all()

        found = self.env["res.partner"].search(
            [("phone_mobile_search", "=", "+3212345678")]
        )
        self.assertIn(partner, found)

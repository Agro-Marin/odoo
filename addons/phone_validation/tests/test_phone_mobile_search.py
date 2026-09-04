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

    def test_negative_operator_excludes_the_record_that_matches(self):
        """A negative search must not return the record the positive one does.

        ``phone_mobile_search`` consults several columns, so negating it means
        negating a disjunction. Spelling that out per column is what went
        wrong: for a term in international form the negative branch compared
        the number against both the ``00`` and the ``+`` spelling and OR'ed
        the two refusals, which no number can fail at once -- so the condition
        held for every row and the search returned the whole table, the exact
        match included.
        """
        partner = self.env["res.partner"].create(
            {
                "name": "International-format contact",
                "phone": "+3212345678",
                "country_id": self.env.ref("base.be").id,
            }
        )
        self.env.flush_all()

        Partner = self.env["res.partner"]
        self.assertIn(
            partner,
            Partner.search([("phone_mobile_search", "=", "+3212345678")]),
            "the positive search is the reference: it must find the contact",
        )
        for operator, value in [
            ("!=", "+3212345678"),
            ("<>", "+3212345678"),
            ("not in", ["+3212345678"]),
        ]:
            with self.subTest(operator=operator):
                self.assertNotIn(
                    partner,
                    Partner.search([("phone_mobile_search", operator, value)]),
                    "a negative search returned the contact it excludes",
                )

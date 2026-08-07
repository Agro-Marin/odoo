from odoo.addons.base.tests.common import TransactionCaseWithUserDemo


class TestMonetaryAccess(TransactionCaseWithUserDemo):
    def test_monetary_access_create(self):
        user_admin = self.env.ref("base.user_admin")
        user_demo = self.user_demo.with_user(user_admin)

        new_user = user_demo.copy({"monetary": 1 / 3})
        new_user.partner_id.company_id = new_user.company_id

        self.assertEqual(
            new_user.currency_id.id,
            False,
            "The cache contains the wrong value for currency.",
        )
        self.assertEqual(
            new_user.monetary,
            1 / 3,
            "Because of previous point, no rounding was done.",
        )

        self.env.invalidate_all()

        self.assertEqual(
            new_user.currency_id.rounding,
            0.01,
            "We now get the correct currency.",
        )
        self.assertEqual(
            new_user.monetary,
            0.33,
            "The value was rounded when added to the cache.",
        )

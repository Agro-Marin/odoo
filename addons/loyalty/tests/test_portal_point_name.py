from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPortalPointName(TransactionCase):
    def test_a_payment_program_names_its_points_after_the_currency(self):
        currency = self.env.ref("base.EUR")
        currency.active = True
        ewallet = self.env["loyalty.program"].create(
            {"name": "Wallet", "program_type": "ewallet", "currency_id": currency.id}
        )
        self.assertEqual(ewallet.portal_point_name, currency.symbol)

    def test_a_loyalty_program_counts_points(self):
        program = self.env["loyalty.program"].create(
            {"name": "Card", "program_type": "loyalty"}
        )
        self.assertEqual(program.portal_point_name, "Points")

    def test_an_explicit_point_name_is_kept(self):
        program = self.env["loyalty.program"].create(
            {"name": "Stars", "program_type": "loyalty", "portal_point_name": "Stars"}
        )
        self.assertEqual(program.portal_point_name, "Stars")

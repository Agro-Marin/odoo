from odoo.tests import tagged

from odoo.addons.l10n_hr_edi.tests.test_hr_edi_common import TestL10nHrEdiCommon


@tagged("post_install_l10n", "post_install", "-at_install")
class TestPaymentUnreportedSearch(TestL10nHrEdiCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.without_addendum = cls.init_invoice(
            "out_invoice", products=cls.product_a, post=True
        )
        cls.reported = cls.init_invoice(
            "out_invoice", products=cls.product_a, post=True
        )
        cls.unreported = cls.init_invoice(
            "out_invoice", products=cls.product_a, post=True
        )
        cls.env["l10n_hr_edi.addendum"].create(
            [
                {
                    "move_id": cls.reported.id,
                    "payment_reported_amount": cls.reported.amount_total
                    - cls.reported.amount_residual,
                },
                {
                    # The invoices are posted and unpaid, so a payment reported
                    # as zero IS the whole story; only a non-zero one disagrees
                    # with what the move says was paid.
                    "move_id": cls.unreported.id,
                    "payment_reported_amount": 1.0,
                },
            ]
        )
        cls.env.flush_all()

    def _search(self, domain):
        scope = [
            ("id", "in", (self.without_addendum | self.reported | self.unreported).ids)
        ]
        return self.env["account.move"].search(scope + domain)

    def test_the_moves_with_unreported_payments_can_be_listed(self):
        for domain in (
            [("l10n_hr_payment_unreported", "=", True)],
            [("l10n_hr_payment_unreported", "!=", False)],
        ):
            with self.subTest(domain=domain):
                self.assertEqual(self._search(domain), self.unreported)

    def test_a_move_with_no_addendum_is_not_unreported(self):
        reported = self._search([("l10n_hr_payment_unreported", "=", False)])
        self.assertIn(self.without_addendum, reported)
        self.assertIn(self.reported, reported)
        self.assertNotIn(self.unreported, reported)

from odoo.fields import Command, Domain
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestPurchaseMailingTarget(AccountTestInvoicingCommon):
    """`purchase.order` must be offered as a recipient model of a mailing campaign.

    `mailing.mailing.mailing_model_id` is filtered on `is_mailing_enabled`
    (mass_mailing/models/mailing.py:249), which reads the `_mailing_enabled`
    class attribute.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.draft_order, cls.cancelled_order = cls.env["purchase.order"].create(
            [
                {
                    "partner_id": cls.partner_a.id,
                    "line_ids": [
                        Command.create(
                            {"product_id": cls.product_a.id, "product_qty": 1.0}
                        )
                    ],
                }
            ]
            * 2
        )
        cls.cancelled_order.state = "cancel"

    def test_purchase_order_is_a_mailing_target(self):
        if "is_mailing_enabled" not in self.env["ir.model"]._fields:
            self.skipTest("mass_mailing is not installed")
        self.assertTrue(self.env["ir.model"]._get("purchase.order").is_mailing_enabled)

    def test_purchase_order_shows_up_in_the_mailing_model_selection(self):
        if "mailing.mailing" not in self.env:
            self.skipTest("mass_mailing is not installed")
        models = self.env["ir.model"].search([("is_mailing_enabled", "=", True)])
        self.assertIn("purchase.order", models.mapped("model"))

    def test_default_domain_leaves_cancelled_orders_out(self):
        domain = self.env["purchase.order"]._mailing_get_default_domain(
            self.env.get("mailing.mailing", None)
        )
        both = self.draft_order | self.cancelled_order
        reached = self.env["purchase.order"].search(
            Domain(domain) & Domain("id", "in", both.ids)
        )
        self.assertEqual(reached, self.draft_order)

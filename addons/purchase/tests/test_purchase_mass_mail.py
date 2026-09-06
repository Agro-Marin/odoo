from odoo.fields import Command
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestPurchaseMassMail(AccountTestInvoicingCommon):
    """Writing to the vendors of several orders at once, from the list or kanban.

    `sale` already offers this through `sale.action_send_mail`; `purchase` is the
    sibling that does not, and `action_send_rfq` refuses a multi-record set.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.order_a, cls.order_b = cls.env["purchase.order"].create(
            [
                {
                    "partner_id": partner.id,
                    "line_ids": [
                        Command.create(
                            {"product_id": cls.product_a.id, "product_qty": 2.0}
                        )
                    ],
                }
                for partner in (cls.partner_a, cls.partner_b)
            ]
        )

    def test_send_mail_action_is_bound_to_list_and_kanban(self):
        action = self.env.ref("purchase.action_send_mail")
        self.assertEqual(action.binding_model_id.model, "purchase.order")
        self.assertIn("list", action.binding_view_types)
        self.assertIn("kanban", action.binding_view_types)

    def test_several_orders_open_the_composer_in_mass_mail_mode(self):
        orders = self.order_a | self.order_b
        context = orders.action_send_rfq()["context"]
        self.assertEqual(context["default_composition_mode"], "mass_mail")
        self.assertEqual(sorted(context["default_res_ids"]), sorted(orders.ids))

    def test_several_orders_carry_no_single_order_context(self):
        context = (self.order_a | self.order_b).action_send_rfq()["context"]
        self.assertNotIn("force_email", context)
        self.assertNotIn("default_template_id", context)
        self.assertNotIn("model_description", context)

    def test_a_single_order_still_opens_in_comment_mode(self):
        context = self.order_a.action_send_rfq()["context"]
        self.assertEqual(context["default_composition_mode"], "comment")
        self.assertEqual(context["model_description"], self.order_a.type_name)

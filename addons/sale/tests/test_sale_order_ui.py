from odoo.fields import Command
from odoo.tests import HttpCase, tagged

from odoo.addons.product.tests.common import ProductVariantsCommon


@tagged("post_install", "-at_install")
class TestSaleOrderUI(HttpCase, ProductVariantsCommon):
    def test_sale_order_keep_uom_on_variant_wizard_quantity_change(self):
        so = self.env["sale.order"].create(
            {
                "partner_id": self.partner.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product_template_sofa.product_variant_ids[
                                0
                            ].id,
                            "product_uom_id": self.uom_dozen.id,
                            "product_qty": 1,
                        }
                    )
                ],
            }
        )

        self.start_tour(
            f"/odoo/sales/{so.id}",
            "sale_order_keep_uom_on_variant_wizard_quantity_change",
            login="admin",
        )

        sol = so.line_ids[0]
        self.assertEqual(sol.product_uom_id, self.uom_dozen)

    def test_sale_order_cancel_confirmation_names_the_action(self):
        """The confirmation for `action_cancel` has to distinguish itself.

        Both buttons read "Cancel" -- the one that cancels the order and the one
        that closes the dialog -- and in es_MX both read "Cancelar". The tour
        goes through the real form arch and the real view-button hook, so it
        fails if the attributes are dropped from `view_sale_order_form`.
        """
        so = self.env["sale.order"].create({"partner_id": self.partner.id})

        self.start_tour(
            f"/odoo/sales/{so.id}",
            "sale_order_cancel_confirmation",
            login="admin",
        )

        self.assertEqual(so.state, "cancel")

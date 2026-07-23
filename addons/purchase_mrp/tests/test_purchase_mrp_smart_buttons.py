# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import Command
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestPurchaseMrpSmartButtons(AccountTestInvoicingCommon):
    """Smart-button navigation and counts linking a PO with the MO it supplies."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.env.company.id)], limit=1
        )
        cls.env.user.group_ids = [
            Command.link(cls.env.ref("mrp.group_mrp_user").id),
            Command.link(cls.env.ref("purchase.group_purchase_user").id),
        ]
        goods = cls.env.ref("product.product_category_goods")
        uom_unit = cls.env.ref("uom.product_uom_unit")
        cls.component = cls.env["product.product"].create(
            {
                "name": "MTO Component",
                "is_storable": True,
                "categ_id": goods.id,
                "uom_id": uom_unit.id,
            }
        )
        cls.finished = cls.env["product.product"].create(
            {
                "name": "Manufactured Product",
                "is_storable": True,
                "categ_id": goods.id,
                "uom_id": uom_unit.id,
            }
        )

    def _create_confirmed_mo_feeding_a_po(self):
        """Confirm an MO whose component is MTO+buy, generating a PO to supply it.

        :return: the confirmed manufacturing order
        :rtype: mrp.production
        """
        self.env.ref("stock.route_warehouse0_mto").active = True
        route_buy = self.warehouse.buy_pull_id.route_id
        route_mto = self.warehouse.mto_pull_id.route_id
        route_mto.rule_ids.procure_method = "make_to_order"
        self.component.write(
            {
                "seller_ids": [Command.create({"partner_id": self.partner_a.id})],
                "route_ids": [Command.link(route_buy.id), Command.link(route_mto.id)],
            }
        )
        bom = self.env["mrp.bom"].create(
            {
                "product_tmpl_id": self.finished.product_tmpl_id.id,
                "product_qty": 1.0,
                "bom_line_ids": [
                    Command.create(
                        {"product_id": self.component.id, "product_qty": 2.0}
                    ),
                ],
            }
        )
        production = self.env["mrp.production"].create(
            {
                "product_id": self.finished.id,
                "bom_id": bom.id,
                "product_qty": 3,
            }
        )
        production.action_confirm()
        return production

    def test_mo_purchase_order_smart_button(self):
        """MO surfaces the PO generated to supply its MTO component."""
        production = self._create_confirmed_mo_feeding_a_po()
        purchase = production.reference_ids.purchase_ids
        self.assertEqual(len(purchase), 1)
        self.assertEqual(production.purchase_order_count, 1)
        self.assertEqual(production._get_purchase_orders(), purchase)
        action = production.action_view_purchase_orders()
        self.assertEqual(action["res_model"], "purchase.order")
        self.assertEqual(action["res_id"], purchase.id)
        self.assertEqual(action["view_mode"], "form")

    def test_purchase_order_mrp_production_smart_button(self):
        """PO surfaces the MO it supplies as a single-record form action."""
        production = self._create_confirmed_mo_feeding_a_po()
        purchase = production.reference_ids.purchase_ids
        self.assertEqual(purchase.mrp_production_count, 1)
        self.assertEqual(purchase._get_mrp_productions(), production)
        action = purchase.action_view_mrp_productions()
        self.assertEqual(action["res_model"], "mrp.production")
        self.assertEqual(action["res_id"], production.id)
        self.assertEqual(action["view_mode"], "form")

    def test_purchase_order_without_mrp_production(self):
        """A PO sourcing no MO reports zero and opens a list action (boundary)."""
        purchase = self.env["purchase.order"].create(
            {
                "partner_id": self.partner_a.id,
                "line_ids": [
                    Command.create(
                        {"product_id": self.component.id, "product_qty": 1.0}
                    ),
                ],
            }
        )
        self.assertEqual(purchase.mrp_production_count, 0)
        self.assertFalse(purchase._get_mrp_productions())
        action = purchase.action_view_mrp_productions()
        self.assertEqual(action["res_model"], "mrp.production")
        self.assertNotIn("res_id", action)
        self.assertEqual(action["view_mode"], "list,form")
        self.assertIn(("id", "in", []), action["domain"])

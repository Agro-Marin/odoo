from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tests.common import new_test_user

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestPurchaseMrpSmartButtons(AccountTestInvoicingCommon):
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
        production = self._create_confirmed_mo_feeding_a_po()
        purchase = production.reference_ids.purchase_ids
        self.assertEqual(purchase.mrp_production_count, 1)
        self.assertEqual(purchase._get_mrp_productions(), production)
        action = purchase.action_view_mrp_productions()
        self.assertEqual(action["res_model"], "mrp.production")
        self.assertEqual(action["res_id"], production.id)
        self.assertEqual(action["view_mode"], "form")

    def test_purchase_order_without_mrp_production(self):
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

    def test_mrp_production_count_denied_without_mrp_group(self):
        production = self._create_confirmed_mo_feeding_a_po()
        purchase = production.reference_ids.purchase_ids
        user = new_test_user(
            self.env,
            login="smart_buttons_user",
            groups="base.group_user,purchase.group_purchase_user",
        )

        with self.assertRaises(AccessError):
            purchase.with_user(user).read(["mrp_production_count"])

    def test_mrp_production_count_recomputes_when_a_move_is_linked(self):
        production = self._create_confirmed_mo_feeding_a_po()
        raw_move = production.move_raw_ids[0]
        other_purchase = self.env["purchase.order"].create(
            {
                "partner_id": self.partner_a.id,
                "line_ids": [
                    Command.create(
                        {"product_id": self.component.id, "product_qty": 1.0}
                    ),
                ],
            }
        )
        other_purchase.action_confirm()
        self.assertEqual(other_purchase.mrp_production_count, 0)

        other_purchase.line_ids.move_ids[0].move_dest_ids = [Command.link(raw_move.id)]

        self.assertEqual(other_purchase._get_mrp_productions(), production)
        self.assertEqual(other_purchase.mrp_production_count, 1)

    def test_purchase_order_count_recomputes_when_a_move_is_linked(self):
        production = self._create_confirmed_mo_feeding_a_po()
        raw_move = production.move_raw_ids[0]
        self.assertEqual(production.purchase_order_count, 1)

        second_purchase = self.env["purchase.order"].create(
            {
                "partner_id": self.partner_a.id,
                "line_ids": [
                    Command.create(
                        {"product_id": self.component.id, "product_qty": 1.0}
                    ),
                ],
            }
        )
        second_purchase.action_confirm()
        raw_move.move_orig_ids = [Command.link(second_purchase.line_ids.move_ids[0].id)]

        self.assertIn(second_purchase, production._get_purchase_orders())
        self.assertEqual(
            production.purchase_order_count,
            len(production._get_purchase_orders()),
        )

    def test_merge_keeps_purchase_links_while_the_order_is_an_rfq(self):
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
                        {"product_id": self.component.id, "product_qty": 1.0}
                    ),
                ],
            }
        )
        productions = self.env["mrp.production"].create(
            [
                {"product_id": self.finished.id, "bom_id": bom.id, "product_qty": qty}
                for qty in (2, 3)
            ]
        )
        productions.action_confirm()

        before = productions.move_raw_ids.created_purchase_line_ids
        self.assertTrue(before, "each order should hold a purchase line link")
        self.assertFalse(
            productions.move_raw_ids.move_orig_ids,
            "the orders are still RFQs, which is the window this guards",
        )

        productions.action_merge()
        merged = (
            self.env["mrp.production"].search(
                [("product_id", "=", self.finished.id), ("state", "!=", "cancel")]
            )
            - productions.exists()
        )
        self.assertEqual(
            merged.move_raw_ids.created_purchase_line_ids.order_id,
            before.order_id,
            "the merged order should still reach every purchase order",
        )

    def test_responsible_is_notified_when_no_supplier_can_replenish(self):
        self.env.ref("stock.route_warehouse0_mto").active = True
        route_buy = self.warehouse.buy_pull_id.route_id
        route_mto = self.warehouse.mto_pull_id.route_id
        route_mto.rule_ids.procure_method = "make_to_order"
        self.component.route_ids = [
            Command.link(route_buy.id),
            Command.link(route_mto.id),
        ]
        bom = self.env["mrp.bom"].create(
            {
                "product_tmpl_id": self.finished.product_tmpl_id.id,
                "product_qty": 1.0,
                "bom_line_ids": [
                    Command.create(
                        {"product_id": self.component.id, "product_qty": 1.0}
                    ),
                ],
            }
        )
        production = self.env["mrp.production"].create(
            {
                "product_id": self.finished.id,
                "bom_id": bom.id,
                "product_qty": 1,
            }
        )
        production.action_confirm()

        self.assertTrue(
            production.reference_ids,
            "the procurement's origin travels on reference_ids",
        )
        notices = production.message_ids.filtered(
            lambda message: "manually replenished" in (message.body or "")
        )
        self.assertTrue(
            notices,
            "the responsible should be told that nothing can supply the component",
        )

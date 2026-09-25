from odoo.tests import tagged

from odoo.addons.mrp.tests.common import TestMrpCommon


@tagged("post_install", "-at_install")
class TestTwoFinishedMovesValuation(TestMrpCommon):
    def test_merged_then_resized_average_order_prices_both_finished_moves(self):
        mo, _bom, product, component_1, component_2 = self.generate_mo(
            qty_final=30, qty_base_1=1, qty_base_2=1
        )
        product.categ_id = self.env["product.category"].create(
            {"name": "Average", "property_cost_method": "average"}
        )
        self.assertEqual(product.cost_method, "average")
        component_1.standard_price = 10
        component_2.standard_price = 7.5
        productions = mo._split_productions({mo: [10, 10, 10]})
        sibling = productions[2]
        productions[:2].action_merge()
        sibling.move_finished_ids.move_dest_ids = self.env["stock.move"].create(
            {
                "product_id": product.id,
                "product_uom_id": product.uom_id.id,
                "location_id": sibling.location_dest_id.id,
                "location_dest_id": self.customer_location.id,
            }
        )
        self.env["change.production.qty"].create(
            {"mo_id": sibling.id, "product_qty": 15}
        ).change_prod_qty()
        self.assertEqual(len(sibling._get_main_finished_moves()), 2)

        sibling.qty_producing = 15
        sibling._update_moves_from_qty_producing()
        sibling.button_mark_done()

        finished_moves = sibling._get_main_finished_moves()
        self.assertEqual(sibling.state, "done")
        self.assertEqual(sum(finished_moves.mapped("quantity")), 15.0)
        self.assertEqual(finished_moves.mapped("price_unit"), [17.5, 17.5])

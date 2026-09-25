from odoo.tests import tagged

from odoo.addons.mrp.tests.common import TestMrpCommon


@tagged("post_install", "-at_install")
class TestTwoFinishedMovesValuation(TestMrpCommon):
    def test_an_average_order_with_a_split_finished_move_prices_both(self):
        mo, _bom, product, component_1, component_2 = self.generate_mo(
            qty_final=15, qty_base_1=1, qty_base_2=1
        )
        product.categ_id = self.env["product.category"].create(
            {"name": "Average", "property_cost_method": "average"}
        )
        self.assertEqual(product.cost_method, "average")
        component_1.standard_price = 10
        component_2.standard_price = 7.5
        self.env["stock.move"].create(mo._get_main_finished_moves()._split(5))
        self.assertEqual(len(mo._get_main_finished_moves()), 2)

        mo.qty_producing = 15
        mo._update_moves_from_qty_producing()
        mo.button_mark_done()

        finished_moves = mo._get_main_finished_moves()
        self.assertEqual(mo.state, "done")
        self.assertEqual(sum(finished_moves.mapped("quantity")), 15.0)
        self.assertEqual(finished_moves.mapped("price_unit"), [17.5, 17.5])

from odoo.tests import Form

from odoo.addons.mrp_account.tests.common import TestBomPriceCommon

PRICE = 718.75 - 100


class TestMrpValuationStandard(TestBomPriceCommon):
    def _get_production_cost_move_lines(self):
        return self.env["account.move.line"].search(
            [
                ("account_id", "=", self.account_production.id),
            ],
            order="date, id",
        )

    def test_fifo_fifo_1(self):
        self.glass.categ_id = self.category_fifo
        self.dining_table.categ_id = self.category_fifo

        self._make_in_move(self.glass, 1, 10)
        self._make_in_move(self.glass, 1, 20)
        mo = self._create_mo(self.bom_1, 2)
        self._produce(mo, 1)
        action = mo.button_mark_done()
        backorder = Form(
            self.env["mrp.production.backorder"].with_context(**action["context"])
        )
        backorder.save().action_backorder()
        mo = mo.production_group_id.production_ids[-1]
        self.assertEqual(self.glass.total_value, 20)
        self.assertEqual(self.dining_table.total_value, PRICE + 10)
        self._produce(mo)
        mo.button_mark_done()
        self.assertEqual(self.glass.total_value, 0)
        self.assertEqual(self.dining_table.total_value, 2 * PRICE + 10 + 20)

    def test_fifo_fifo_2(self):
        self.glass.categ_id = self.category_fifo

        self._make_in_move(self.glass, 1, 10)
        self._make_in_move(self.glass, 1, 20)
        mo = self._create_mo(self.bom_1, 2)
        self._produce(mo)
        mo.button_mark_done()
        self.assertEqual(self.glass.total_value, 0)
        self.assertEqual(self.dining_table.total_value, 2 * PRICE + 10 + 20)
        self._make_out_move(self.dining_table, 1)
        self.assertEqual(self.dining_table.total_value, (2 * PRICE + 10 + 20) / 2)

    def test_fifo_unbuild(self):
        self.glass.categ_id = self.category_fifo
        self._make_in_move(self.glass, 1, 10)
        self._make_in_move(self.glass, 1, 20)
        mo = self._create_mo(self.bom_1, 1)
        self._produce(mo)
        mo.button_mark_done()
        self.assertEqual(self.glass.total_value, 20)
        unbuild_form = Form(self.env["mrp.unbuild"])
        unbuild_form.mo_id = mo
        unbuild_form.save().action_unbuild()
        self.assertEqual(self.glass.total_value, 30)

    def test_fifo_produce_deliver_return_unbuild(self):
        self.glass.categ_id = self.category_fifo
        self._make_in_move(self.glass, 1, 10)

        mo = self._create_mo(self.bom_1, 1)
        self._produce(mo)
        mo.button_mark_done()

        out_move = self._make_out_move(self.dining_table, 1.0, create_picking=True)
        self._make_return(out_move, 1.0)

        unbuild_form = Form(self.env["mrp.unbuild"])
        unbuild_form.mo_id = mo
        unbuild_form.save().action_unbuild()

        moves = self.env["stock.move"].search(
            [("product_id", "=", self.dining_table.id)]
        )
        self.assertRecordValues(
            moves,
            [
                {
                    "value": PRICE + 10,
                    "quantity": 1.0,
                    "is_in": True,
                    "remaining_value": 0.0,
                    "remaining_qty": 0.0,
                },
                {
                    "value": PRICE + 10,
                    "quantity": 1.0,
                    "is_in": False,
                    "remaining_value": 0.0,
                    "remaining_qty": 0.0,
                },
                {
                    "value": PRICE + 10,
                    "quantity": 1.0,
                    "is_in": True,
                    "remaining_value": 0.0,
                    "remaining_qty": 0.0,
                },
                {
                    "value": PRICE + 10,
                    "quantity": 1.0,
                    "is_in": False,
                    "remaining_value": 0.0,
                    "remaining_qty": 0.0,
                },
            ],
        )

    def test_fifo_avco_1(self):
        self.glass.categ_id = self.category_fifo
        self.dining_table.categ_id = self.category_avco

        self._make_in_move(self.glass, 1, 10)
        self._make_in_move(self.glass, 1, 20)
        mo = self._create_mo(self.bom_1, 2)
        self._produce(mo, 1)
        action = mo.button_mark_done()
        backorder = Form(
            self.env["mrp.production.backorder"].with_context(**action["context"])
        )
        backorder.save().action_backorder()
        mo = mo.production_group_id.production_ids[-1]
        self.assertEqual(self.glass.total_value, 20)
        self.assertEqual(self.dining_table.total_value, PRICE + 10)
        self._produce(mo)

        mo.button_mark_done()
        self.assertEqual(self.glass.total_value, 0)
        self.assertEqual(self.dining_table.total_value, 2 * PRICE + 10 + 20)

    def test_fifo_avco_2(self):
        self.glass.categ_id = self.category_fifo
        self.dining_table.categ_id = self.category_avco
        self.dining_table.categ_id = self.category_fifo

        self._make_in_move(self.glass, 1, 10)
        self._make_in_move(self.glass, 1, 20)
        mo = self._create_mo(self.bom_1, 2)
        self._produce(mo)
        mo.button_mark_done()
        self.assertEqual(self.glass.total_value, 0)
        self.assertEqual(self.dining_table.total_value, PRICE * 2 + 10 + 20)
        self._make_out_move(self.dining_table, 1)
        self.assertEqual(self.dining_table.total_value, (PRICE * 2 + 10 + 20) / 2)

    def test_fifo_std_1(self):
        self.glass.categ_id = self.category_fifo
        self.dining_table.categ_id = self.category_standard
        self.dining_table.standard_price = 8.8

        self._make_in_move(self.glass, 1, 10)
        self._make_in_move(self.glass, 1, 20)
        mo = self._create_mo(self.bom_1, 2)
        self._produce(mo, 1)
        mo._post_inventory()
        self.assertEqual(self.glass.total_value, 20)
        self.assertEqual(self.dining_table.total_value, 8.8)
        self._produce(mo)
        mo.button_mark_done()
        self.assertEqual(self.glass.total_value, 0)
        self.assertEqual(self.dining_table.total_value, 8.8 * 2)

    def test_fifo_std_2(self):
        self.glass.categ_id = self.category_fifo
        self.dining_table.categ_id = self.category_standard
        self.dining_table.standard_price = 8.8

        self._make_in_move(self.glass, 1, 10)
        self._make_in_move(self.glass, 1, 20)
        mo = self._create_mo(self.bom_1, 2)
        self._produce(mo)
        mo.button_mark_done()
        self.assertEqual(self.glass.total_value, 0)
        self.assertEqual(self.dining_table.total_value, 8.8 * 2)
        self._make_out_move(self.dining_table, 1)
        self.assertEqual(self.dining_table.total_value, 8.8)

    def test_std_avco_1(self):
        self.glass.categ_id = self.category_standard
        self.dining_table.categ_id = self.category_avco

        self._make_in_move(self.glass, 1)
        self._make_in_move(self.glass, 1)
        mo = self._create_mo(self.bom_1, 2)
        self._produce(mo, 1)
        mo._post_inventory()
        self.assertEqual(self.glass.total_value, 100)
        self.assertEqual(self.dining_table.total_value, PRICE + 100)
        self._produce(mo)
        mo.button_mark_done()
        self.assertEqual(self.glass.total_value, 0)
        self.assertEqual(self.dining_table.total_value, 2 * (PRICE + 100))

    def test_std_avco_2(self):
        self.glass.categ_id = self.category_standard
        self.dining_table.categ_id = self.category_avco

        self._make_in_move(self.glass, 1)
        self._make_in_move(self.glass, 1)
        mo = self._create_mo(self.bom_1, 2)
        self._produce(mo)
        mo.button_mark_done()
        self.assertEqual(self.glass.total_value, 0)
        self.assertEqual(self.dining_table.total_value, 2 * (PRICE + 100))
        self.assertEqual(self.dining_table.standard_price, PRICE + 100)

        self._make_out_move(self.dining_table, 1)
        self.assertEqual(self.dining_table.total_value, PRICE + 100)

        self.glass.standard_price = 0

        self._make_in_move(self.glass, 3)
        mo = self._create_mo(self.bom_1, 3)
        self._produce(mo)
        mo.button_mark_done()
        self.assertEqual(self.dining_table.total_value, 4 * PRICE + 100)
        self.assertEqual(self.dining_table.standard_price, (4 * PRICE + 100) / 4)

    def test_std_std_1(self):
        self.glass.categ_id = self.category_standard
        self.dining_table.categ_id = self.category_standard

        self._make_in_move(self.glass, 1)
        self._make_in_move(self.glass, 1)
        mo = self._create_mo(self.bom_1, 2)
        self._produce(mo, 1)
        mo._post_inventory()
        self.assertEqual(self.glass.total_value, 100)
        self.assertEqual(self.dining_table.total_value, 1000)
        self._produce(mo)
        mo.button_mark_done()
        self.assertEqual(self.glass.total_value, 0)
        self.assertEqual(self.dining_table.total_value, 2000)

    def test_std_std_2(self):
        self.glass.categ_id = self.category_standard
        self.dining_table.categ_id = self.category_standard

        self._make_in_move(self.glass, 1)
        self._make_in_move(self.glass, 1)
        mo = self._create_mo(self.bom_1, 2)
        self._produce(mo)
        mo.button_mark_done()
        self.assertEqual(self.glass.total_value, 0)
        self.assertEqual(self.dining_table.total_value, 2000)
        self._make_out_move(self.dining_table, 1)
        self.assertEqual(self.dining_table.total_value, 1000)

    def test_avco_avco_1(self):
        self.glass.categ_id = self.category_avco
        self.dining_table.categ_id = self.category_avco

        self._make_in_move(self.glass, 1, 10)
        self._make_in_move(self.glass, 1, 20)
        mo = self._create_mo(self.bom_1, 2)
        self._produce(mo, 1)
        mo._post_inventory()
        self.assertEqual(self.glass.total_value, 15)
        self.assertEqual(self.dining_table.total_value, PRICE + 15)
        self._produce(mo)
        mo.button_mark_done()
        self.assertEqual(self.glass.total_value, 0)
        self.assertEqual(self.dining_table.total_value, 2 * PRICE + 30)

    def test_avco_avco_2(self):
        self.glass.categ_id = self.category_avco
        self.dining_table.categ_id = self.category_avco

        self._make_in_move(self.glass, 1, 10)
        self._make_in_move(self.glass, 1, 20)
        mo = self._create_mo(self.bom_1, 2)
        self._produce(mo)
        mo.button_mark_done()
        self.assertEqual(self.glass.total_value, 0)
        self.assertEqual(self.dining_table.total_value, 2 * PRICE + 30)
        self._make_out_move(self.dining_table, 1)
        self.assertEqual(self.dining_table.total_value, (2 * PRICE + 30) / 2)

    def test_validate_draft_kit(self):
        self.plywood_sheet.qty_available = 0
        self.plywood_sheet.categ_id = self.category_avco

        receipt = self.env["stock.picking"].create(
            {
                "location_id": self.customer_location.id,
                "location_dest_id": self.stock_location.id,
                "picking_type_id": self.picking_type_in.id,
                "state": "draft",
                "move_line_ids": [
                    (
                        0,
                        0,
                        {
                            "product_id": self.table_head.id,
                            "quantity": 12,
                            "product_uom_id": self.table_head.uom_id.id,
                            "location_id": self.customer_location.id,
                            "location_dest_id": self.stock_location.id,
                        },
                    )
                ],
            }
        )
        receipt.move_ids.picked = True
        receipt.button_validate()

        self.assertEqual(self.plywood_sheet.qty_available, 12)
        self.assertEqual(self.plywood_sheet.total_value, 2400)

    def test_production_account_00(self):
        self.dining_table.categ_id.property_cost_method = "standard"

        self._make_out_move(
            self.dining_table, 1, location_dest_id=self.prod_location.id
        )

        in_aml = self._get_production_cost_move_lines()
        self.assertEqual(in_aml.debit, 1000)
        self.assertEqual(in_aml.product_id, self.dining_table)

        self._make_in_move(self.dining_table, 1, location_id=self.prod_location.id)

        out_aml = self._get_production_cost_move_lines() - in_aml
        self.assertEqual(out_aml.credit, 1000)
        self.assertEqual(in_aml.product_id, self.dining_table)

    def test_average_cost_unbuild_component_change_move_qty(self):
        mo = self._create_mo(self.bom_1, 1)
        self._produce(mo)
        mo.button_mark_done()
        action = mo.button_unbuild()
        wizard = Form(self.env[action["res_model"]].with_context(action["context"]))
        wizard.product_qty = 1
        unbuild = wizard.save()
        unbuild.action_validate()
        comp_move = mo.unbuild_ids.produce_line_ids.filtered(
            lambda move: move.product_id.id == self.glass.id
        )
        with Form(comp_move.move_line_ids[0]) as form:
            form.quantity = 0

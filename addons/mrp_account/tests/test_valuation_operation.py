from odoo.tests import Form

from odoo.addons.mrp_account.tests.common import TestBomPriceOperationCommon

PRICE = 718.75 + 2 * 321.25 - 100


class TestMrpValuationOperationStandard(TestBomPriceOperationCommon):
    def test_fifo_byproduct(self):
        self.glass.categ_id = self.category_fifo
        self.glass.qty_available = 0
        self.scrap_wood.categ_id = self.category_avco
        byproduct_cost_share = 0.13

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
        self.assertEqual(
            self.dining_table.total_value,
            self.company.currency_id.round((PRICE + 10) * (1 - byproduct_cost_share)),
        )
        self.assertEqual(
            self.scrap_wood.total_value,
            self.company.currency_id.round((PRICE + 10) * byproduct_cost_share),
        )
        self._produce(mo)
        mo.button_mark_done()
        self.assertEqual(self.glass.total_value, 0)
        self.assertEqual(
            self.dining_table.total_value,
            self.company.currency_id.round(
                (2 * PRICE + 30) * (1 - byproduct_cost_share)
            ),
        )
        moves = self.env["stock.move"].search(
            [
                ("product_id", "=", self.scrap_wood.id),
            ]
        )
        self.assertRecordValues(
            moves,
            [
                {"value": self.company.currency_id.round((PRICE + 10) * 0.01)},
                {"value": self.company.currency_id.round((PRICE + 10) * 0.12)},
                {"value": self.company.currency_id.round((PRICE + 20) * 0.01)},
                {"value": self.company.currency_id.round((PRICE + 20) * 0.12)},
            ],
        )

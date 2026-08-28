from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import Form, tagged

from odoo.addons.sale_stock.tests.common import TestSaleStockCommon
from odoo.addons.stock_account.tests.common import TestStockValuationCommon


@tagged("post_install", "-at_install")
class TestAngloSaxonValuation(TestStockValuationCommon, TestSaleStockCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner_b = cls.env["res.partner"].create({"name": "Partner B"})

    def _fifo_in_one_eight_one_ten(self):
        self._make_in_move(self.product_fifo_auto, 1, 8)
        self._make_in_move(self.product_fifo_auto, 1, 10)

    def test_standard_ordered_invoice_pre_delivery(self):
        self.product_standard_auto.invoice_policy = "ordered"
        self.product_standard_auto.standard_price = 10.0

        self._inv_adj_two_units(self.product_standard_auto)

        sale_order = self._so_deliver(self.product_standard_auto, 2, 12, picking=False)

        self.product_standard_auto.standard_price = 14.0

        invoice = sale_order._create_invoices()
        invoice.action_post()

        amls = invoice.line_ids
        self.assertEqual(len(amls), 4)
        stock_out_aml = amls.filtered(
            lambda aml: aml.account_id == self.account_stock_valuation
        )
        self.assertEqual(stock_out_aml.debit, 0)
        self.assertEqual(stock_out_aml.credit, 28)
        cogs_aml = amls.filtered(lambda aml: aml.account_id == self.account_expense)
        self.assertEqual(cogs_aml.debit, 28)
        self.assertEqual(cogs_aml.credit, 0)
        receivable_aml = amls.filtered(
            lambda aml: aml.account_id == self.account_receivable
        )
        self.assertEqual(receivable_aml.debit, 24)
        self.assertEqual(receivable_aml.credit, 0)
        income_aml = amls.filtered(lambda aml: aml.account_id == self.account_income)
        self.assertEqual(income_aml.debit, 0)
        self.assertEqual(income_aml.credit, 24)

    def test_standard_ordered_invoice_post_partial_delivery_1(self):
        self.product_standard_auto.invoice_policy = "ordered"
        self.product_standard_auto.standard_price = 10.0

        sale_order = self._so_deliver(self.product_standard_auto, 2, 12, picking=False)

        sale_order.picking_ids.move_ids.write({"quantity": 1, "picked": True})
        Form.from_action(
            self.env, sale_order.picking_ids.button_validate()
        ).save().process()

        invoice = sale_order._create_invoices()
        invoice.invoice_line_ids[0].quantity = 1
        invoice.action_post()

        amls = invoice.line_ids
        self.assertEqual(len(amls), 4)
        stock_out_aml = amls.filtered(
            lambda aml: aml.account_id == self.account_stock_valuation
        )
        self.assertEqual(stock_out_aml.debit, 0)
        self.assertEqual(stock_out_aml.credit, 10)
        cogs_aml = amls.filtered(lambda aml: aml.account_id == self.account_expense)
        self.assertEqual(cogs_aml.debit, 10)
        self.assertEqual(cogs_aml.credit, 0)
        receivable_aml = amls.filtered(
            lambda aml: aml.account_id == self.account_receivable
        )
        self.assertEqual(receivable_aml.debit, 12)
        self.assertEqual(receivable_aml.credit, 0)
        income_aml = amls.filtered(lambda aml: aml.account_id == self.account_income)
        self.assertEqual(income_aml.debit, 0)
        self.assertEqual(income_aml.credit, 12)

        self.product_standard_auto.standard_price = 14.0

        sale_order.picking_ids[0].move_ids.write({"quantity": 1, "picked": True})
        sale_order.picking_ids[0].button_validate()

        self.product_standard_auto.standard_price = 16.0

        invoice2 = sale_order._create_invoices()
        invoice2.action_post()
        amls = invoice2.line_ids
        self.assertEqual(len(amls), 4)
        stock_out_aml = amls.filtered(
            lambda aml: aml.account_id == self.account_stock_valuation
        )
        self.assertEqual(stock_out_aml.debit, 0)
        self.assertEqual(stock_out_aml.credit, 22)
        cogs_aml = amls.filtered(lambda aml: aml.account_id == self.account_expense)
        self.assertEqual(cogs_aml.debit, 22)
        self.assertEqual(cogs_aml.credit, 0)
        receivable_aml = amls.filtered(
            lambda aml: aml.account_id == self.account_receivable
        )
        self.assertEqual(receivable_aml.debit, 12)
        self.assertEqual(receivable_aml.credit, 0)
        income_aml = amls.filtered(lambda aml: aml.account_id == self.account_income)
        self.assertEqual(income_aml.debit, 0)
        self.assertEqual(income_aml.credit, 12)

    def test_standard_ordered_invoice_post_delivery(self):
        self.product_standard_auto.invoice_policy = "ordered"
        self.product_standard_auto.standard_price = 10
        self._use_inventory_location_accounting()

        self._inv_adj_two_units(self.product_standard_auto)
        amls = self.env["account.move.line"].search(
            [("product_id", "=", self.product_standard_auto.id)]
        )
        self.assertRecordValues(
            amls,
            [
                {"account_id": self.account_inventory.id, "debit": 0.0, "credit": 20.0},
                {
                    "account_id": self.account_stock_valuation.id,
                    "debit": 20.0,
                    "credit": 0.0,
                },
            ],
        )

        sale_order = self._so_deliver(self.product_standard_auto, 2, 12, picking=False)

        sale_order.picking_ids.move_ids.write({"quantity": 1, "picked": True})
        Form.from_action(
            self.env, sale_order.picking_ids.button_validate()
        ).save().process()

        self.product_standard_auto.standard_price = 14.0

        sale_order.picking_ids.filtered("backorder_id").move_ids.write(
            {"quantity": 1, "picked": True}
        )
        sale_order.picking_ids.filtered("backorder_id").button_validate()

        invoice = sale_order._create_invoices()
        invoice.action_post()

        amls = invoice.line_ids
        self.assertEqual(len(amls), 4)
        stock_out_aml = amls.filtered(
            lambda aml: aml.account_id == self.account_stock_valuation
        )
        self.assertEqual(stock_out_aml.debit, 0)
        self.assertEqual(stock_out_aml.credit, 28)
        cogs_aml = amls.filtered(lambda aml: aml.account_id == self.account_expense)
        self.assertEqual(cogs_aml.debit, 28)
        self.assertEqual(cogs_aml.credit, 0)
        receivable_aml = amls.filtered(
            lambda aml: aml.account_id == self.account_receivable
        )
        self.assertEqual(receivable_aml.debit, 24)
        self.assertEqual(receivable_aml.credit, 0)
        income_aml = amls.filtered(lambda aml: aml.account_id == self.account_income)
        self.assertEqual(income_aml.debit, 0)
        self.assertEqual(income_aml.credit, 24)

        closing_move = self._close()
        self.assertRecordValues(
            closing_move.line_ids,
            [
                {
                    "account_id": self.account_stock_variation.id,
                    "debit": 0.0,
                    "credit": 8.0,
                },
                {
                    "account_id": self.account_stock_valuation.id,
                    "debit": 8.0,
                    "credit": 0.0,
                },
            ],
        )

    def test_standard_delivered_invoice_pre_delivery(self):
        self.product_standard_auto.invoice_policy = "transferred"
        self.product_standard_auto.standard_price = 10

        self._inv_adj_two_units(self.product_standard_auto)

        sale_order = self._so_deliver(self.product_standard_auto, 2, 12, picking=False)

        with self.assertRaises(UserError):
            sale_order._create_invoices()

    def test_standard_delivered_invoice_post_delivery(self):
        self.product_standard_auto.invoice_policy = "transferred"
        self.product_standard_auto.standard_price = 10
        self._use_inventory_location_accounting()

        self._inv_adj_two_units(self.product_standard_auto)
        amls = self.env["account.move.line"].search(
            [("product_id", "=", self.product_standard_auto.id)]
        )
        self.assertRecordValues(
            amls,
            [
                {"account_id": self.account_inventory.id, "debit": 0.0, "credit": 20.0},
                {
                    "account_id": self.account_stock_valuation.id,
                    "debit": 20.0,
                    "credit": 0.0,
                },
            ],
        )

        sale_order = self._so_deliver(self.product_standard_auto, 2, 12, picking=False)

        sale_order.picking_ids.move_ids.write({"quantity": 1, "picked": True})
        Form.from_action(
            self.env, sale_order.picking_ids.button_validate()
        ).save().process()

        self.product_standard_auto.standard_price = 14.0

        sale_order.picking_ids.filtered("backorder_id").move_ids.write(
            {"quantity": 1, "picked": True}
        )
        sale_order.picking_ids.filtered("backorder_id").button_validate()

        invoice = sale_order._create_invoices()
        invoice.action_post()

        amls = invoice.line_ids
        self.assertEqual(len(amls), 4)
        stock_out_aml = amls.filtered(
            lambda aml: aml.account_id == self.account_stock_valuation
        )
        self.assertEqual(stock_out_aml.debit, 0)
        self.assertEqual(stock_out_aml.credit, 28)
        cogs_aml = amls.filtered(lambda aml: aml.account_id == self.account_expense)
        self.assertEqual(cogs_aml.debit, 28)
        self.assertEqual(cogs_aml.credit, 0)
        receivable_aml = amls.filtered(
            lambda aml: aml.account_id == self.account_receivable
        )
        self.assertEqual(receivable_aml.debit, 24)
        self.assertEqual(receivable_aml.credit, 0)
        income_aml = amls.filtered(lambda aml: aml.account_id == self.account_income)
        self.assertEqual(income_aml.debit, 0)
        self.assertEqual(income_aml.credit, 24)

        closing_move = self._close()
        self.assertRecordValues(
            closing_move.line_ids,
            [
                {
                    "account_id": self.account_stock_variation.id,
                    "debit": 0.0,
                    "credit": 8.0,
                },
                {
                    "account_id": self.account_stock_valuation.id,
                    "debit": 8.0,
                    "credit": 0.0,
                },
            ],
        )

    def test_avco_ordered_invoice_pre_delivery(self):
        self.product_avco_auto.invoice_policy = "ordered"
        self.product_avco_auto.standard_price = 10

        self._inv_adj_two_units(self.product_avco_auto)

        sale_order = self._so_deliver(self.product_avco_auto, 2, 12, picking=False)

        invoice = sale_order._create_invoices()
        invoice.action_post()

        amls = invoice.line_ids
        self.assertEqual(len(amls), 4)
        stock_out_aml = amls.filtered(
            lambda aml: aml.account_id == self.account_stock_valuation
        )
        self.assertEqual(stock_out_aml.debit, 0)
        self.assertEqual(stock_out_aml.credit, 20)
        cogs_aml = amls.filtered(lambda aml: aml.account_id == self.account_expense)
        self.assertEqual(cogs_aml.debit, 20)
        self.assertEqual(cogs_aml.credit, 0)
        receivable_aml = amls.filtered(
            lambda aml: aml.account_id == self.account_receivable
        )
        self.assertEqual(receivable_aml.debit, 24)
        self.assertEqual(receivable_aml.credit, 0)
        income_aml = amls.filtered(lambda aml: aml.account_id == self.account_income)
        self.assertEqual(income_aml.debit, 0)
        self.assertEqual(income_aml.credit, 24)

    def test_avco_ordered_invoice_post_partial_delivery(self):
        self.product_avco_auto.invoice_policy = "ordered"
        self.product_avco_auto.standard_price = 10

        self._inv_adj_two_units(self.product_avco_auto)

        sale_order = self._so_deliver(self.product_avco_auto, 2, 12, picking=False)

        sale_order.picking_ids.move_ids.write({"quantity": 1, "picked": True})
        Form.from_action(
            self.env, sale_order.picking_ids.button_validate()
        ).save().process()

        invoice = sale_order._create_invoices()
        invoice.action_post()

        amls = invoice.line_ids
        self.assertEqual(len(amls), 4)
        stock_out_aml = amls.filtered(
            lambda aml: aml.account_id == self.account_stock_valuation
        )
        self.assertEqual(stock_out_aml.debit, 0)
        self.assertEqual(stock_out_aml.credit, 20)
        cogs_aml = amls.filtered(lambda aml: aml.account_id == self.account_expense)
        self.assertEqual(cogs_aml.debit, 20)
        self.assertEqual(cogs_aml.credit, 0)
        receivable_aml = amls.filtered(
            lambda aml: aml.account_id == self.account_receivable
        )
        self.assertEqual(receivable_aml.debit, 24)
        self.assertEqual(receivable_aml.credit, 0)
        income_aml = amls.filtered(lambda aml: aml.account_id == self.account_income)
        self.assertEqual(income_aml.debit, 0)
        self.assertEqual(income_aml.credit, 24)

    def test_avco_ordered_invoice_post_delivery(self):
        self.product_avco_auto.invoice_policy = "ordered"
        self.product_avco_auto.standard_price = 10

        self._inv_adj_two_units(self.product_avco_auto)

        sale_order = self._so_deliver(self.product_avco_auto, 2, 12)

        invoice = sale_order._create_invoices()
        invoice.action_post()

        amls = invoice.line_ids
        self.assertEqual(len(amls), 4)
        stock_out_aml = amls.filtered(
            lambda aml: aml.account_id == self.account_stock_valuation
        )
        self.assertEqual(stock_out_aml.debit, 0)
        self.assertEqual(stock_out_aml.credit, 20)
        cogs_aml = amls.filtered(lambda aml: aml.account_id == self.account_expense)
        self.assertEqual(cogs_aml.debit, 20)
        self.assertEqual(cogs_aml.credit, 0)
        receivable_aml = amls.filtered(
            lambda aml: aml.account_id == self.account_receivable
        )
        self.assertEqual(receivable_aml.debit, 24)
        self.assertEqual(receivable_aml.credit, 0)
        income_aml = amls.filtered(lambda aml: aml.account_id == self.account_income)
        self.assertEqual(income_aml.debit, 0)
        self.assertEqual(income_aml.credit, 24)

    def test_avco_ordered_return_and_receipt(self):
        product = self.product_avco_auto
        product.invoice_policy = "ordered"
        product.is_storable = True
        product.categ_id.property_cost_method = "average"
        product.categ_id.property_valuation = "real_time"
        product.list_price = 100
        product.standard_price = 50

        so = self._so_deliver(product, 5, product.list_price)
        pick = so.picking_ids

        product.standard_price = 40

        stock_return_picking_form = Form(
            self.env["stock.return.picking"].with_context(
                active_ids=pick.ids,
                active_id=pick.sorted().ids[0],
                active_model="stock.picking",
            )
        )
        return_wiz = stock_return_picking_form.save()
        return_wiz.product_return_moves.quantity = 1
        return_wiz.product_return_moves.to_refund = False
        res = return_wiz.action_create_returns()

        return_pick = self.env["stock.picking"].browse(res["res_id"])
        return_pick.move_ids.write({"quantity": 1, "picked": True})
        return_pick.button_validate()

        move = self.env["stock.move"].create(
            {
                "location_id": self.env.ref("stock.stock_location_suppliers").id,
                "location_dest_id": self.stock_location.id,
                "product_id": product.id,
                "product_uom_id": product.uom_id.id,
                "quantity": 1,
                "picked": True,
            }
        )
        move._action_done()

        invoice = so._create_invoices()
        invoice.action_post()
        self.assertEqual(invoice.state, "posted")

    def test_avco_delivered_invoice_pre_delivery(self):
        self.product_avco_auto.invoice_policy = "transferred"
        self.product_avco_auto.standard_price = 10

        self._inv_adj_two_units(self.product_avco_auto)

        sale_order = self._so_deliver(self.product_avco_auto, 2, 12, picking=False)

        with self.assertRaises(UserError):
            sale_order._create_invoices()

    def test_avco_delivered_invoice_post_partial_delivery(self):
        self.product_avco_auto.invoice_policy = "transferred"
        self.product_avco_auto.standard_price = 10

        self._inv_adj_two_units(self.product_avco_auto)

        sale_order = self._so_deliver(self.product_avco_auto, 2, 12, picking=False)

        sale_order.picking_ids.move_ids.write({"quantity": 1, "picked": True})
        Form.from_action(
            self.env, sale_order.picking_ids.button_validate()
        ).save().process()

        invoice = sale_order._create_invoices()
        invoice.action_post()

        amls = invoice.line_ids
        self.assertEqual(len(amls), 4)
        stock_out_aml = amls.filtered(
            lambda aml: aml.account_id == self.account_stock_valuation
        )
        self.assertEqual(stock_out_aml.debit, 0)
        self.assertEqual(stock_out_aml.credit, 10)
        cogs_aml = amls.filtered(lambda aml: aml.account_id == self.account_expense)
        self.assertEqual(cogs_aml.debit, 10)
        self.assertEqual(cogs_aml.credit, 0)
        receivable_aml = amls.filtered(
            lambda aml: aml.account_id == self.account_receivable
        )
        self.assertEqual(receivable_aml.debit, 12)
        self.assertEqual(receivable_aml.credit, 0)
        income_aml = amls.filtered(lambda aml: aml.account_id == self.account_income)
        self.assertEqual(income_aml.debit, 0)
        self.assertEqual(income_aml.credit, 12)

    def test_avco_delivered_invoice_post_delivery(self):
        self.product_avco_auto.invoice_policy = "transferred"
        self.product_avco_auto.standard_price = 10

        self._inv_adj_two_units(self.product_avco_auto)

        sale_order = self._so_deliver(self.product_avco_auto, 2, 12, picking=False)
        sale_order.picking_ids.move_ids.write({"quantity": 2, "picked": True})
        sale_order.picking_ids.button_validate()

        invoice = sale_order._create_invoices()
        invoice.action_post()

        amls = invoice.line_ids
        self.assertEqual(len(amls), 4)
        stock_out_aml = amls.filtered(
            lambda aml: aml.account_id == self.account_stock_valuation
        )
        self.assertEqual(stock_out_aml.debit, 0)
        self.assertEqual(stock_out_aml.credit, 20)
        cogs_aml = amls.filtered(lambda aml: aml.account_id == self.account_expense)
        self.assertEqual(cogs_aml.debit, 20)
        self.assertEqual(cogs_aml.credit, 0)
        receivable_aml = amls.filtered(
            lambda aml: aml.account_id == self.account_receivable
        )
        self.assertEqual(receivable_aml.debit, 24)
        self.assertEqual(receivable_aml.credit, 0)
        income_aml = amls.filtered(lambda aml: aml.account_id == self.account_income)
        self.assertEqual(income_aml.debit, 0)
        self.assertEqual(income_aml.credit, 24)

    def test_avco_partially_owned_and_delivered_invoice_post_delivery(self):
        self.product_avco_auto.invoice_policy = "transferred"
        self.product_avco_auto.standard_price = 10

        self.env["stock.quant"]._update_available_quantity(
            self.product_avco_auto, self.stock_location, 1, owner_id=self.partner_b
        )
        self.env["stock.quant"]._update_available_quantity(
            self.product_avco_auto, self.stock_location, 1
        )

        sale_order = self._so_deliver(self.product_avco_auto, 2, 12, picking=False)
        sale_order.picking_ids.move_line_ids.write({"quantity": 1, "picked": True})
        sale_order.picking_ids.button_validate()

        invoice01 = sale_order._create_invoices()
        invoice01.invoice_line_ids[0].quantity = 1
        invoice01.action_post()

        invoice02 = sale_order._create_invoices()
        invoice02.action_post()

        self.assertRecordValues(
            invoice01.line_ids,
            [
                {"account_id": self.account_income.id, "debit": 0, "credit": 12},
                {"account_id": self.account_receivable.id, "debit": 12, "credit": 0},
                {
                    "account_id": self.account_stock_valuation.id,
                    "debit": 0,
                    "credit": 5,
                },
                {"account_id": self.account_expense.id, "debit": 5, "credit": 0},
            ],
        )
        self.assertRecordValues(
            invoice02.line_ids,
            [
                {"account_id": self.account_income.id, "debit": 0, "credit": 12},
                {"account_id": self.account_receivable.id, "debit": 12, "credit": 0},
                {
                    "account_id": self.account_stock_valuation.id,
                    "debit": 0,
                    "credit": 5,
                },
                {"account_id": self.account_expense.id, "debit": 5, "credit": 0},
            ],
        )

    def test_avco_fully_owned_and_delivered_invoice_post_delivery(self):
        self.product_avco_auto.invoice_policy = "transferred"
        self.product_avco_auto.standard_price = 10

        self.env["stock.quant"]._update_available_quantity(
            self.product_avco_auto, self.stock_location, 2, owner_id=self.partner_b
        )

        sale_order = self._so_deliver(self.product_avco_auto, 2, 12, picking=False)
        sale_order.picking_ids.move_line_ids.write({"quantity": 2, "picked": True})
        sale_order.picking_ids.button_validate()

        invoice = sale_order._create_invoices()
        invoice.action_post()

        amls = invoice.line_ids
        self.assertRecordValues(
            amls,
            [
                {"account_id": self.account_income.id, "debit": 0, "credit": 24},
                {"account_id": self.account_receivable.id, "debit": 24, "credit": 0},
            ],
        )

    def test_fifo_ordered_invoice_pre_delivery(self):
        self.product_fifo_auto.invoice_policy = "ordered"

        self._fifo_in_one_eight_one_ten()

        sale_order = self._so_deliver(self.product_fifo_auto, 2, 12, picking=False)

        invoice = sale_order._create_invoices()
        invoice.action_post()

        amls = invoice.line_ids
        self.assertEqual(len(amls), 4)
        stock_out_aml = amls.filtered(
            lambda aml: aml.account_id == self.account_stock_valuation
        )
        self.assertEqual(stock_out_aml.debit, 0)
        self.assertEqual(stock_out_aml.credit, 18)
        cogs_aml = amls.filtered(lambda aml: aml.account_id == self.account_expense)
        self.assertEqual(cogs_aml.debit, 18)
        self.assertEqual(cogs_aml.credit, 0)
        receivable_aml = amls.filtered(
            lambda aml: aml.account_id == self.account_receivable
        )
        self.assertEqual(receivable_aml.debit, 24)
        self.assertEqual(receivable_aml.credit, 0)
        income_aml = amls.filtered(lambda aml: aml.account_id == self.account_income)
        self.assertEqual(income_aml.debit, 0)
        self.assertEqual(income_aml.credit, 24)

    def test_fifo_ordered_invoice_post_partial_delivery(self):
        self.product_fifo_auto.invoice_policy = "ordered"

        self._fifo_in_one_eight_one_ten()

        sale_order = self._so_deliver(self.product_fifo_auto, 2, 12, picking=False)

        sale_order.picking_ids.move_ids.write({"quantity": 1, "picked": True})
        Form.from_action(
            self.env, sale_order.picking_ids.button_validate()
        ).save().process()

        self.product_fifo_auto.standard_price = 12

        invoice = sale_order._create_invoices()
        invoice.invoice_line_ids[0].quantity = 2
        invoice.action_post()

        amls = invoice.line_ids
        self.assertEqual(len(amls), 4)
        stock_out_aml = amls.filtered(
            lambda aml: aml.account_id == self.account_stock_valuation
        )
        self.assertEqual(stock_out_aml.debit, 0)
        self.assertEqual(stock_out_aml.credit, 16)
        cogs_aml = amls.filtered(lambda aml: aml.account_id == self.account_expense)
        self.assertEqual(cogs_aml.debit, 16)
        self.assertEqual(cogs_aml.credit, 0)
        receivable_aml = amls.filtered(
            lambda aml: aml.account_id == self.account_receivable
        )
        self.assertEqual(receivable_aml.debit, 24)
        self.assertEqual(receivable_aml.credit, 0)
        income_aml = amls.filtered(lambda aml: aml.account_id == self.account_income)
        self.assertEqual(income_aml.debit, 0)
        self.assertEqual(income_aml.credit, 24)

    def test_fifo_ordered_invoice_post_delivery(self):
        self.product_fifo_auto.invoice_policy = "ordered"

        self._fifo_in_one_eight_one_ten()

        sale_order = self._so_deliver(self.product_fifo_auto, 2, 12, picking=False)

        sale_order.picking_ids.move_ids.write({"quantity": 2, "picked": True})
        sale_order.picking_ids.button_validate()

        invoice = sale_order._create_invoices()
        invoice.action_post()

        amls = invoice.line_ids
        self.assertEqual(len(amls), 4)
        stock_out_aml = amls.filtered(
            lambda aml: aml.account_id == self.account_stock_valuation
        )
        self.assertEqual(stock_out_aml.debit, 0)
        self.assertEqual(stock_out_aml.credit, 18)
        cogs_aml = amls.filtered(lambda aml: aml.account_id == self.account_expense)
        self.assertEqual(cogs_aml.debit, 18)
        self.assertEqual(cogs_aml.credit, 0)
        receivable_aml = amls.filtered(
            lambda aml: aml.account_id == self.account_receivable
        )
        self.assertEqual(receivable_aml.debit, 24)
        self.assertEqual(receivable_aml.credit, 0)
        income_aml = amls.filtered(lambda aml: aml.account_id == self.account_income)
        self.assertEqual(income_aml.debit, 0)
        self.assertEqual(income_aml.credit, 24)

    def test_fifo_delivered_invoice_pre_delivery(self):
        self.product_fifo_auto.invoice_policy = "transferred"
        self.product_fifo_auto.standard_price = 10

        self._fifo_in_one_eight_one_ten()

        sale_order = self._so_deliver(self.product_fifo_auto, 2, 12, picking=False)

        with self.assertRaises(UserError):
            sale_order._create_invoices()

    def test_fifo_delivered_invoice_post_partial_delivery(self):
        self.product_fifo_auto.invoice_policy = "transferred"

        self._fifo_in_one_eight_one_ten()

        sale_order = self._so_deliver(self.product_fifo_auto, 2, 12, picking=False)

        sale_order.picking_ids.move_ids.write({"quantity": 1, "picked": True})
        Form.from_action(
            self.env, sale_order.picking_ids.button_validate()
        ).save().process()

        self.product_fifo_auto.standard_price = 12

        invoice = sale_order._create_invoices()
        invoice.line_ids[0].quantity = 2
        invoice.action_post()

        amls = invoice.line_ids
        self.assertEqual(len(amls), 4)
        stock_out_aml = amls.filtered(
            lambda aml: aml.account_id == self.account_stock_valuation
        )
        self.assertEqual(stock_out_aml.debit, 0)
        self.assertEqual(stock_out_aml.credit, 16)
        cogs_aml = amls.filtered(lambda aml: aml.account_id == self.account_expense)
        self.assertEqual(cogs_aml.debit, 16)
        self.assertEqual(cogs_aml.credit, 0)
        receivable_aml = amls.filtered(
            lambda aml: aml.account_id == self.account_receivable
        )
        self.assertEqual(receivable_aml.debit, 24)
        self.assertEqual(receivable_aml.credit, 0)
        income_aml = amls.filtered(lambda aml: aml.account_id == self.account_income)
        self.assertEqual(income_aml.debit, 0)
        self.assertEqual(income_aml.credit, 24)

    def test_fifo_delivered_invoice_post_delivery(self):
        self.product_fifo_auto.invoice_policy = "transferred"
        self.product_fifo_auto.standard_price = 10

        self._fifo_in_one_eight_one_ten()

        sale_order = self._so_deliver(self.product_fifo_auto, 2, 12, picking=False)

        sale_order.picking_ids.move_ids.write({"quantity": 2, "picked": True})
        sale_order.picking_ids.button_validate()

        invoice = sale_order._create_invoices()
        invoice.action_post()

        amls = invoice.line_ids
        self.assertEqual(len(amls), 4)
        stock_out_aml = amls.filtered(
            lambda aml: aml.account_id == self.account_stock_valuation
        )
        self.assertEqual(stock_out_aml.debit, 0)
        self.assertEqual(stock_out_aml.credit, 18)
        cogs_aml = amls.filtered(lambda aml: aml.account_id == self.account_expense)
        self.assertEqual(cogs_aml.debit, 18)
        self.assertEqual(cogs_aml.credit, 0)
        receivable_aml = amls.filtered(
            lambda aml: aml.account_id == self.account_receivable
        )
        self.assertEqual(receivable_aml.debit, 24)
        self.assertEqual(receivable_aml.credit, 0)
        income_aml = amls.filtered(lambda aml: aml.account_id == self.account_income)
        self.assertEqual(income_aml.debit, 0)
        self.assertEqual(income_aml.credit, 24)

    def test_fifo_delivered_invoice_post_delivery_2(self):
        self.product_fifo_auto.invoice_policy = "transferred"
        self.product_fifo_auto.standard_price = 10

        self._make_in_move(self.product_fifo_auto, 8, 10)

        sale_order = self._so_deliver(self.product_fifo_auto, 10, 12)

        in_move = self._make_in_move(self.product_fifo_auto, 12, 2)
        self.assertEqual(in_move.value, 24)

        invoice = sale_order._create_invoices()
        invoice.action_post()

        amls = invoice.line_ids
        self.assertEqual(len(amls), 4)
        stock_out_aml = amls.filtered(
            lambda aml: aml.account_id == self.account_stock_valuation
        )
        self.assertEqual(stock_out_aml.debit, 0)
        self.assertEqual(stock_out_aml.credit, 100)
        cogs_aml = amls.filtered(lambda aml: aml.account_id == self.account_expense)
        self.assertEqual(cogs_aml.debit, 100)
        self.assertEqual(cogs_aml.credit, 0)
        receivable_aml = amls.filtered(
            lambda aml: aml.account_id == self.account_receivable
        )
        self.assertEqual(receivable_aml.debit, 120)
        self.assertEqual(receivable_aml.credit, 0)
        income_aml = amls.filtered(lambda aml: aml.account_id == self.account_income)
        self.assertEqual(income_aml.debit, 0)
        self.assertEqual(income_aml.credit, 120)

    def test_fifo_delivered_invoice_post_delivery_3(self):
        self.product_fifo_auto.invoice_policy = "transferred"

        self._make_in_move(self.product_fifo_auto, 5, 8)

        self._make_in_move(self.product_fifo_auto, 8, 12)

        sale_order = self._so_deliver(self.product_fifo_auto, 1, 20)
        invoice = sale_order._create_invoices()
        invoice.action_post()

        sale_order = self._so_deliver(self.product_fifo_auto, 6, 20)
        invoice = sale_order._create_invoices()
        invoice.action_post()

        amls = invoice.line_ids
        cogs_aml = amls.filtered(lambda aml: aml.account_id == self.account_expense)
        self.assertEqual(cogs_aml.debit, 56)
        self.assertEqual(cogs_aml.credit, 0)

    def test_fifo_delivered_invoice_post_delivery_4(self):
        self.product_fifo_auto.invoice_policy = "transferred"
        self.product_fifo_auto.standard_price = 10

        self._make_in_move(self.product_fifo_auto, 8, 10)
        self._create_bill(self.product_fifo_auto, 8, 10)

        sale_order = self._so_deliver(self.product_fifo_auto, 10, 12)

        invoice = sale_order._create_invoices()
        invoice.action_post()

        self._make_in_move(self.product_fifo_auto, 2, 12)
        self._create_bill(self.product_fifo_auto, 2, 12)

        closing_move = self._close()
        self.assertRecordValues(
            closing_move.line_ids,
            [
                {
                    "account_id": self.account_stock_valuation.id,
                    "debit": 0.0,
                    "credit": 4.0,
                },
                {
                    "account_id": self.account_stock_variation.id,
                    "debit": 4.0,
                    "credit": 0.0,
                },
            ],
        )

    def test_fifo_delivered_invoice_post_delivery_with_return(self):
        self.product_fifo_auto.invoice_policy = "transferred"

        self._make_in_move(self.product_fifo_auto, 2, 10)

        so_1 = self._so_deliver(self.product_fifo_auto, 2, 12)

        stock_return_picking_form = Form(
            self.env["stock.return.picking"].with_context(
                active_ids=so_1.picking_ids.ids,
                active_id=so_1.picking_ids.ids[0],
                active_model="stock.picking",
            )
        )
        stock_return_picking = stock_return_picking_form.save()
        stock_return_picking.product_return_moves.quantity = 1.0
        stock_return_picking_action = stock_return_picking.action_create_returns()
        return_pick = self.env["stock.picking"].browse(
            stock_return_picking_action["res_id"]
        )
        return_pick.action_assign()
        return_pick.move_ids.write({"quantity": 1, "picked": True})
        return_pick._action_done()

        so_2 = self._so_deliver(self.product_fifo_auto, 1, 12)

        self._make_in_move(self.product_fifo_auto, 1, 20)

        stock_redeliver_picking_form = Form(
            self.env["stock.return.picking"].with_context(
                active_ids=return_pick.ids,
                active_id=return_pick.ids[0],
                active_model="stock.picking",
            )
        )
        stock_redeliver_picking = stock_redeliver_picking_form.save()
        stock_redeliver_picking.product_return_moves.quantity = 1.0
        stock_redeliver_picking_action = stock_redeliver_picking.action_create_returns()
        redeliver_pick = self.env["stock.picking"].browse(
            stock_redeliver_picking_action["res_id"]
        )
        redeliver_pick.action_assign()
        redeliver_pick.move_ids.write({"quantity": 1, "picked": True})
        redeliver_pick._action_done()

        invoice_1 = so_1._create_invoices()
        invoice_1.action_post()
        invoice_2 = so_2._create_invoices()
        invoice_2.action_post()

        amls_1 = invoice_1.line_ids
        self.assertEqual(len(amls_1), 4)
        stock_out_aml_1 = amls_1.filtered(
            lambda aml: aml.account_id == self.account_stock_valuation
        )
        self.assertEqual(stock_out_aml_1.debit, 0)
        self.assertEqual(stock_out_aml_1.credit, 30)
        cogs_aml_1 = amls_1.filtered(lambda aml: aml.account_id == self.account_expense)
        self.assertEqual(cogs_aml_1.debit, 30)
        self.assertEqual(cogs_aml_1.credit, 0)
        receivable_aml_1 = amls_1.filtered(
            lambda aml: aml.account_id == self.account_receivable
        )
        self.assertEqual(receivable_aml_1.debit, 24)
        self.assertEqual(receivable_aml_1.credit, 0)
        income_aml_1 = amls_1.filtered(
            lambda aml: aml.account_id == self.account_income
        )
        self.assertEqual(income_aml_1.debit, 0)
        self.assertEqual(income_aml_1.credit, 24)

        amls_2 = invoice_2.line_ids
        self.assertEqual(len(amls_2), 4)
        stock_out_aml_2 = amls_2.filtered(
            lambda aml: aml.account_id == self.account_stock_valuation
        )
        self.assertEqual(stock_out_aml_2.debit, 0)
        self.assertEqual(stock_out_aml_2.credit, 10)
        cogs_aml_2 = amls_2.filtered(lambda aml: aml.account_id == self.account_expense)
        self.assertEqual(cogs_aml_2.debit, 10)
        self.assertEqual(cogs_aml_2.credit, 0)
        receivable_aml_2 = amls_2.filtered(
            lambda aml: aml.account_id == self.account_receivable
        )
        self.assertEqual(receivable_aml_2.debit, 12)
        self.assertEqual(receivable_aml_2.credit, 0)
        income_aml_2 = amls_2.filtered(
            lambda aml: aml.account_id == self.account_income
        )
        self.assertEqual(income_aml_2.debit, 0)
        self.assertEqual(income_aml_2.credit, 12)

    def test_fifo_uom_computation(self):
        self.product_fifo_auto.categ_id.property_valuation = "real_time"
        quantity = 50.0
        self.product_fifo_auto.list_price = 1.5
        self.product_fifo_auto.standard_price = 2.0
        unit_12 = self.env["uom.uom"].create(
            {
                "name": "Pack of 12 units",
                "relative_factor": 12,
                "relative_uom_id": self.env.ref("uom.product_uom_unit").id,
            }
        )

        so_1 = (
            self.env["sale.order"]
            .sudo()
            .create(
                {
                    "partner_id": self.owner.id,
                    "line_ids": [
                        Command.create(
                            {
                                "name": self.product_fifo_auto.name,
                                "product_id": self.product_fifo_auto.id,
                                "product_qty": 1,
                                "product_uom_id": unit_12.id,
                                "price_unit": 18,
                                "tax_ids": False,
                            }
                        )
                    ],
                }
            )
        )
        so_1.action_confirm()
        so_1.picking_ids.move_ids.write({"quantity": 12, "picked": True})
        so_1.picking_ids.button_validate()

        invoice_1 = so_1._create_invoices()
        invoice_1.action_post()

        aml = invoice_1.line_ids
        self.assertEqual(aml[0].debit, 0.0)
        self.assertEqual(aml[0].credit, 18.0)
        self.assertEqual(aml[1].debit, 18.0)
        self.assertEqual(aml[1].credit, 0.0)
        self.assertEqual(aml[2].debit, 0.0)
        self.assertEqual(aml[2].credit, 24.0)
        self.assertEqual(aml[3].debit, 24.0)
        self.assertEqual(aml[3].credit, 0.0)

        self._make_in_move(self.product_fifo_auto, quantity, 1.0)

        so_2 = (
            self.env["sale.order"]
            .sudo()
            .create(
                {
                    "partner_id": self.owner.id,
                    "line_ids": [
                        Command.create(
                            {
                                "name": self.product_fifo_auto.name,
                                "product_id": self.product_fifo_auto.id,
                                "product_qty": 1,
                                "product_uom_id": unit_12.id,
                                "price_unit": 18,
                                "tax_ids": False,
                            }
                        )
                    ],
                }
            )
        )
        so_2.action_confirm()
        so_2.picking_ids.move_ids.write({"quantity": 12, "picked": True})
        so_2.picking_ids.button_validate()

        invoice_2 = so_2._create_invoices()
        invoice_2.action_post()

        aml = invoice_2.line_ids
        self.assertEqual(aml[0].debit, 0.0)
        self.assertEqual(aml[0].credit, 18.0)
        self.assertEqual(aml[1].debit, 18.0)
        self.assertEqual(aml[1].credit, 0.0)
        self.assertEqual(aml[2].debit, 0.0)
        self.assertEqual(aml[2].credit, 12.0)
        self.assertEqual(aml[3].debit, 12.0)
        self.assertEqual(aml[3].credit, 0.0)

    def test_fifo_return_and_credit_note(self):
        svl_values = [10, 20, 60]
        for val in svl_values:
            self._make_in_move(self.product_fifo_auto, 1, val)

        so = self._so_deliver(self.product_fifo_auto, 3, 100, picking=False)

        pickings = []
        picking = so.picking_ids
        while picking:
            pickings.append(picking)
            picking.move_ids.write({"quantity": 1, "picked": True})
            action = picking.button_validate()
            if isinstance(action, dict):
                Form.from_action(self.env, action).save().process()
            picking = picking.backorder_ids

        invoice = so._create_invoices()
        invoice.action_post()

        self._make_in_move(self.product_fifo_auto, 1, 100)

        ctx = {"active_id": pickings[1].id, "active_model": "stock.picking"}
        return_wizard = Form(self.env["stock.return.picking"].with_context(ctx)).save()
        return_wizard.product_return_moves.quantity = 1
        return_picking = return_wizard._create_return()
        return_picking.move_ids.write({"quantity": 1, "picked": True})
        return_picking.button_validate()

        ctx = {"active_model": "account.move", "active_ids": invoice.ids}
        refund_wizard = (
            self.env["account.move.reversal"]
            .with_context(ctx)
            .create(
                {
                    "journal_id": invoice.journal_id.id,
                }
            )
        )
        action = refund_wizard.refund_moves()
        reverse_invoice = self.env["account.move"].browse(action["res_id"])
        reverse_invoice.invoice_line_ids[0].quantity = 1
        reverse_invoice.action_post()

        amls = reverse_invoice.line_ids
        stock_out_aml = amls.filtered(
            lambda aml: aml.account_id == self.account_stock_valuation
        )
        self.assertEqual(
            stock_out_aml.debit, 20, "Should be to the value of the returned product"
        )
        self.assertEqual(stock_out_aml.credit, 0)
        cogs_aml = amls.filtered(lambda aml: aml.account_id == self.account_expense)
        self.assertEqual(cogs_aml.debit, 0)
        self.assertEqual(
            cogs_aml.credit, 20, "Should be to the value of the returned product"
        )

        closing_move = self._close()
        self.assertRecordValues(
            closing_move.line_ids,
            [
                {
                    "account_id": self.account_stock_variation.id,
                    "debit": 0.0,
                    "credit": 190.0,
                },
                {
                    "account_id": self.account_stock_valuation.id,
                    "debit": 190.0,
                    "credit": 0.0,
                },
            ],
        )

    def test_fifo_return_and_create_invoice(self):
        self.product_fifo_auto.invoice_policy = "transferred"

        svl_values = [10, 20, 60]
        for val in svl_values:
            self._make_in_move(self.product_fifo_auto, 1, val)
        so = self._so_deliver(self.product_fifo_auto, 3, 100, picking=False)

        pickings = []
        picking = so.picking_ids
        while picking:
            pickings.append(picking)
            picking.move_ids.write({"quantity": 1, "picked": True})
            action = picking.button_validate()
            if isinstance(action, dict):
                Form.from_action(self.env, action).save().process()
            picking = picking.backorder_ids

        invoice = so._create_invoices()
        invoice.action_post()

        self._make_in_move(self.product_fifo_auto, 1, 100)

        ctx = {"active_id": pickings[1].id, "active_model": "stock.picking"}
        return_wizard = Form(self.env["stock.return.picking"].with_context(ctx)).save()
        return_wizard.product_return_moves.quantity = 1
        return_picking = return_wizard._create_return()
        return_picking.move_ids.write({"quantity": 1, "picked": True})
        return_picking.button_validate()

        self.env["sale.advance.payment.inv"].with_context(
            {
                "active_model": "sale.order",
                "active_ids": so.ids,
            }
        ).sudo().create({}).create_invoices()
        reverse_invoice = so.invoice_ids[-1]
        reverse_invoice.invoice_line_ids[0].quantity = 1
        reverse_invoice.action_post()

        amls = reverse_invoice.line_ids
        stock_out_aml = amls.filtered(
            lambda aml: aml.account_id == self.account_stock_valuation
        )
        self.assertEqual(
            stock_out_aml.debit, 20, "Should be to the value of the returned product"
        )
        self.assertEqual(stock_out_aml.credit, 0)
        cogs_aml = amls.filtered(lambda aml: aml.account_id == self.account_expense)
        self.assertEqual(cogs_aml.debit, 0)
        self.assertEqual(
            cogs_aml.credit, 20, "Should be to the value of the returned product"
        )

        closing_move = self._close()
        self.assertRecordValues(
            closing_move.line_ids,
            [
                {
                    "account_id": self.account_stock_variation.id,
                    "debit": 0.0,
                    "credit": 190.0,
                },
                {
                    "account_id": self.account_stock_valuation.id,
                    "debit": 190.0,
                    "credit": 0.0,
                },
            ],
        )

    def test_fifo_several_invoices_reset_repost(self):
        self.product_fifo_auto.invoice_policy = "transferred"

        svl_values = [10, 15, 65]
        total_value = sum(svl_values)
        for val in svl_values:
            self._make_in_move(self.product_fifo_auto, 1, val)

        so = self._so_deliver(self.product_fifo_auto, 3, 100, picking=False)

        invoices = self.env["account.move"]
        picking = so.picking_ids
        while picking:
            picking.move_ids.write({"quantity": 1, "picked": True})
            action = picking.button_validate()
            if isinstance(action, dict):
                Form.from_action(self.env, action).save().process()
            picking = picking.backorder_ids

            invoice = so._create_invoices()
            invoice.action_post()
            invoices |= invoice

        out_account = self.account_stock_valuation
        invoice01, _invoice02, invoice03 = invoices
        cogs = invoices.line_ids.filtered(lambda l: l.account_id == out_account)
        self.assertEqual(cogs.mapped("credit"), svl_values)

        for i, inv in enumerate(invoices):
            inv.action_draft()
            inv.action_post()
            cogs = invoices.line_ids.filtered(lambda l: l.account_id == out_account)
            self.assertEqual(
                cogs.mapped("credit"),
                svl_values,
                "Incorrect values while posting again invoice %s" % (i + 1),
            )

        invoices.action_draft()
        invoices.action_post()
        cogs = invoices.line_ids.filtered(lambda l: l.account_id == out_account)
        self.assertEqual(sum(cogs.mapped("credit")), total_value)

        (invoice01 | invoice03).action_draft()
        (invoice01 | invoice03).action_post()
        cogs = invoices.line_ids.filtered(lambda l: l.account_id == out_account)
        self.assertEqual(sum(cogs.mapped("credit")), total_value)

    def test_fifo_reverse_and_create_new_invoice(self):
        accountman = self.env["res.users"].create(
            {
                "name": "Super Accountman",
                "login": "super_accountman",
                "password": "super_accountman",
                "group_ids": [
                    (6, 0, self.env.ref("account.group_account_invoice").ids)
                ],
            }
        )

        self._make_in_move(self.product_fifo_auto, 1, 10)
        self._make_in_move(self.product_fifo_auto, 1, 50)
        so = self._so_deliver(self.product_fifo_auto, 1, 100)
        invoice01 = so._create_invoices()

        self.env.invalidate_all()
        invoice01.with_user(accountman.id).action_post()

        move_reversal = (
            self.env["account.move.reversal"]
            .with_context(active_model="account.move", active_ids=invoice01.ids)
            .create(
                {
                    "journal_id": invoice01.journal_id.id,
                }
            )
        )
        reversal = move_reversal.modify_moves()
        invoice02 = self.env["account.move"].browse(reversal["res_id"])
        invoice02.action_post()

        amls = invoice02.line_ids
        stock_out_aml = amls.filtered(
            lambda aml: aml.account_id == self.account_stock_valuation
        )
        self.assertEqual(stock_out_aml.debit, 0)
        self.assertEqual(stock_out_aml.credit, 10)
        cogs_aml = amls.filtered(lambda aml: aml.account_id == self.account_expense)
        self.assertEqual(cogs_aml.debit, 10)
        self.assertEqual(cogs_aml.credit, 0)

    def test_anglo_saxon_cogs_with_down_payment(self):
        self.product_fifo_auto.invoice_policy = "transferred"
        self.product_fifo_auto.standard_price = 10
        self.env["stock.quant"].with_context(inventory_mode=True).create(
            {
                "product_id": self.product_fifo_auto.id,
                "inventory_quantity": 20,
                "location_id": self.stock_location.id,
            }
        ).action_apply_inventory()

        so = self._so_deliver(self.product_fifo_auto, 10, 100, picking=False)

        self.env["sale.advance.payment.inv"].sudo().create(
            {
                "advance_payment_method": "percentage",
                "amount": 100,
                "sale_order_ids": so.ids,
            }
        ).create_invoices()

        down_payment_invoices = so.invoice_ids
        down_payment_invoices.action_post()

        so.picking_ids.move_ids.quantity = 4
        so.picking_ids.move_ids.picked = True
        Form.from_action(self.env, so.picking_ids.button_validate()).save().process()

        self.env["sale.advance.payment.inv"].with_context(
            active_ids=so.ids,
        ).sudo().create({}).create_invoices()
        credit_note = so.invoice_ids.filtered(lambda i: i.state != "posted")
        self.assertEqual(len(credit_note), 1)
        self.assertEqual(
            len(
                credit_note.invoice_line_ids.filtered(
                    lambda line: line.display_type == "product"
                )
            ),
            2,
        )
        down_payment_line = credit_note.invoice_line_ids.filtered(
            lambda line: line.sale_line_ids.is_downpayment
        )
        down_payment_line.quantity = 0.4
        credit_note.action_post()
        backorder = so.picking_ids.filtered(lambda p: p.state != "done")
        backorder.move_ids.quantity = 6
        backorder.move_ids.picked = True
        backorder.button_validate()

        self.env["sale.advance.payment.inv"].with_context(
            active_ids=so.ids,
        ).sudo().create({}).create_invoices()

        invoice = so.invoice_ids.filtered(lambda i: i.state != "posted")
        invoice.action_post()

        account_stock_out = self.account_stock_valuation
        account_expense = self.account_expense
        invoice_1_cogs = credit_note.line_ids.filtered(
            lambda l: l.display_type == "cogs"
        )
        invoice_2_cogs = invoice.line_ids.filtered(lambda l: l.display_type == "cogs")
        self.assertRecordValues(
            invoice_1_cogs,
            [
                {
                    "debit": 0,
                    "credit": 40,
                    "account_id": account_stock_out.id,
                    "reconciled": False,
                },
                {
                    "debit": 40,
                    "credit": 0,
                    "account_id": account_expense.id,
                    "reconciled": False,
                },
            ],
        )
        self.assertRecordValues(
            invoice_2_cogs,
            [
                {
                    "debit": 0,
                    "credit": 60,
                    "account_id": account_stock_out.id,
                    "reconciled": False,
                },
                {
                    "debit": 60,
                    "credit": 0,
                    "account_id": account_expense.id,
                    "reconciled": False,
                },
            ],
        )

    def test_anglo_saxon_cogs_validate_invoice(self):
        self._make_in_move(self.product_fifo_auto, 12, 100)

        sale_order = (
            self.env["sale.order"]
            .sudo()
            .create(
                {
                    "partner_id": self.owner.id,
                    "warehouse_id": self.warehouse.id,
                    "line_ids": [
                        Command.create(
                            {
                                "product_id": self.product_fifo_auto.id,
                                "product_qty": 10,
                                "price_unit": 100,
                            }
                        ),
                        Command.create(
                            {
                                "product_id": self.product_fifo_auto.id,
                                "product_qty": 2,
                                "price_unit": 100,
                            }
                        ),
                    ],
                }
            )
        )
        sale_order.action_confirm()
        delivery = sale_order.picking_ids
        delivery.move_ids.filtered(lambda m: m.product_uom_qty == 2).quantity = 0
        delivery.move_ids.picked = True
        r = delivery.button_validate()
        Form(self.env[r["res_model"]].with_context(r["context"])).save().process()
        backorder_delivery = sale_order.picking_ids.filtered(
            lambda p: p.state != "done"
        )
        backorder_delivery.move_ids.quantity = 2
        backorder_delivery.button_validate()
        self.env["sale.advance.payment.inv"].with_context(
            active_ids=sale_order.ids,
        ).sudo().create({}).create_invoices()

        invoice = sale_order.invoice_ids
        qty_ten_invoice_line = invoice.invoice_line_ids.filtered(
            lambda l: l.quantity == 10
        )
        qty_ten_invoice_line.quantity = 5
        invoice.invoice_date = fields.Date.today()
        invoice.action_post()
        self.product_fifo_autostandard_price = 50
        self.env["sale.advance.payment.inv"].with_context(
            active_ids=sale_order.ids,
        ).sudo().create({}).create_invoices()
        invoice2 = sale_order.invoice_ids.filtered(lambda i: i.state != "posted")
        invoice2.invoice_date = fields.Date.today()
        invoice2.action_post()
        invoice2_cogs_lines = invoice2.line_ids.filtered(
            lambda l: l.display_type == "cogs"
        )
        self.assertRecordValues(
            invoice2_cogs_lines,
            [
                {"credit": 500, "debit": 0},
                {"credit": 0, "debit": 500},
            ],
        )

    def test_cogs_valued_by_lots(self):
        self.product_avco_auto.product_tmpl_id.categ_id.property_cost_method = "average"
        self.product_avco_auto.write(
            {
                "lot_valuated": True,
                "is_storable": True,
                "tracking": "lot",
            }
        )
        self.lot1, self.lot2 = self.env["stock.lot"].create(
            [
                {"name": "lot1", "product_id": self.product_avco_auto.id},
                {"name": "lot2", "product_id": self.product_avco_auto.id},
            ]
        )
        self._make_in_move(self.product_avco_auto, 2, 10, lot_ids=[self.lot1])
        self._make_in_move(self.product_avco_auto, 2, 16, lot_ids=[self.lot2])
        self.assertEqual(self.product_avco_auto.standard_price, 13)
        self.assertEqual(self.lot1.standard_price, 10)
        self.assertEqual(self.lot2.standard_price, 16)
        so = self._so_deliver(self.product_avco_auto, 1, 1)
        invoice = so._create_invoices()
        invoice.action_post()
        invoice_cogs_lines = invoice.line_ids.filtered(
            lambda l: l.display_type == "cogs"
        ).sorted("debit")
        self.assertRecordValues(
            invoice_cogs_lines,
            [
                {"credit": 10, "debit": 0},
                {"credit": 0, "debit": 10},
            ],
        )
        self.assertEqual(self.lot1.standard_price, 10)
        self.assertEqual(self.lot2.standard_price, 16)
        self.assertEqual(self.product_avco_auto.standard_price, 14)

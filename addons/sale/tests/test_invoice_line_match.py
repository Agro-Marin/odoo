from odoo.fields import Command
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestInvoiceLineMatch(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env["res.partner"].create({"name": "Match customer"})
        cls.immediate_payment_term = cls.env.ref(
            "account.account_payment_term_immediate"
        )
        cls.product = cls.env["product.product"].create(
            {
                "name": "Matched part",
                "type": "consu",
                "sale_ok": True,
                "list_price": 10.0,
            }
        )
        cls.Match = cls.env["sale.invoice.line.match"]

    def _confirmed_order(self, qty=3, price=10.0):
        order = self.env["sale.order"].create(
            {
                "partner_id": self.customer.id,
                "payment_term_id": self.immediate_payment_term.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product.id,
                            "product_qty": qty,
                            "price_unit": price,
                        }
                    )
                ],
            }
        )
        order.action_confirm()
        self.env.flush_all()
        return order

    def _invoice(self, qty=3, price=10.0):
        invoice = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": self.customer.id,
                "invoice_line_ids": [
                    Command.create(
                        {
                            "product_id": self.product.id,
                            "quantity": qty,
                            "price_unit": price,
                        }
                    )
                ],
            }
        )
        self.env.flush_all()
        return invoice

    def _rows(self):
        return self.Match.search([("partner_id", "=", self.customer.id)])

    def test_confirmed_order_line_awaits_matching(self):
        order = self._confirmed_order()
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows.product_uom_qty, 3.0)
        self.assertEqual(rows.product_uom_price, 10.0)
        self.assertEqual(rows.order_line_id, order.line_ids)

    def test_draft_order_is_not_offered_for_matching(self):
        self.env["sale.order"].create(
            {
                "partner_id": self.customer.id,
                "payment_term_id": self.immediate_payment_term.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product.id,
                            "product_qty": 2,
                        }
                    )
                ],
            }
        )
        self.env.flush_all()
        self.assertFalse(self._rows())

    def test_editing_the_price_writes_back_to_the_order_line(self):
        order = self._confirmed_order()
        row = self._rows()
        row.product_uom_price = 12.0
        self.assertEqual(order.line_ids.price_unit, 12.0)

    def test_editing_the_quantity_preserves_the_agreed_price(self):
        order = self._confirmed_order(qty=3, price=10.0)
        row = self._rows()
        row.product_uom_price = 12.0
        row.product_uom_qty = 5.0
        self.assertEqual(order.line_ids.product_qty, 5.0)
        self.assertEqual(order.line_ids.price_unit, 12.0)

    def test_row_opens_its_sale_order(self):
        order = self._confirmed_order()
        action = self._rows().action_open_line()
        self.assertEqual(action["res_model"], "sale.order")
        self.assertEqual(action["res_id"], order.id)

    def test_draft_invoice_line_is_offered_for_matching(self):
        invoice = self._invoice()
        rows = self._rows()
        self.assertEqual(rows.aml_id, invoice.invoice_line_ids)
        self.assertEqual(rows.account_move_id, invoice)

    def test_matching_links_the_invoice_line_to_the_order_line(self):
        order = self._confirmed_order()
        invoice = self._invoice()
        self._rows().action_match_lines()
        self.assertEqual(invoice.invoice_line_ids.sale_line_ids, order.line_ids)

    def test_a_matched_invoice_line_leaves_the_match_list(self):
        self._confirmed_order()
        self._invoice()
        self._rows().action_match_lines()
        self.env.flush_all()
        self.assertFalse(self._rows().aml_id)

    def test_matching_an_order_line_alone_creates_the_invoice(self):
        order = self._confirmed_order()
        action = self._rows().action_match_lines()
        invoice = self.env["account.move"].browse(action["res_id"])
        self.assertEqual(invoice.move_type, "out_invoice")
        self.assertEqual(invoice.partner_id, self.customer)
        self.assertEqual(invoice.currency_id, order.line_ids.currency_id)
        self.assertEqual(invoice.invoice_line_ids.product_id, self.product)

    def test_the_invoice_reports_whether_every_line_is_matched(self):
        self._confirmed_order()
        invoice = self._invoice()
        self.assertFalse(invoice.is_sale_matched)
        self._rows().action_match_lines()
        self.assertTrue(invoice.is_sale_matched)

    def test_auto_complete_pulls_the_order_lines_onto_the_invoice(self):
        order = self._confirmed_order()
        invoice = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": self.customer.id,
            }
        )
        self.env.flush_all()
        document = self.env["sale.invoice.match"].browse(-order.id)
        self.assertEqual(document.order_id, order)

        form_invoice = invoice
        form_invoice.sale_customer_invoice_id = document
        form_invoice._onchange_sale_auto_complete()
        self.assertEqual(form_invoice.invoice_line_ids.product_id, self.product)
        self.assertEqual(form_invoice.invoice_line_ids.sale_line_ids, order.line_ids)

    def test_matching_action_from_the_order_lists_its_own_lines(self):
        order = self._confirmed_order()
        action = order.action_invoice_matching()
        self.assertEqual(action["res_model"], "sale.invoice.line.match")
        self.assertEqual(
            self.Match.search(action["domain"]).order_line_id, order.line_ids
        )

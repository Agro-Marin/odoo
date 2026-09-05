from odoo import Command
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("-at_install", "post_install")
class TestPurchaseBillAutoComplete(AccountTestInvoicingCommon):
    """Auto-Complete must match the bill lines already there before adding more.

    A bill drafted by hand -- or landed from OCR -- carries product lines with no
    purchase order behind them. Picking the PO used to subtract only the lines
    *already linked*, so every order line was appended on top and the buyer
    deleted the duplicates by hand.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.order = cls.env["purchase.order"].create(
            {
                "partner_id": cls.partner_a.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": cls.product_a.id,
                            "product_qty": 5,
                            "price_unit": 100.0,
                        },
                    ),
                ],
            },
        )
        cls.order.action_confirm()

        cls.two_line_order = cls.env["purchase.order"].create(
            {
                "partner_id": cls.partner_a.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": cls.product_a.id,
                            "product_qty": 5,
                            "price_unit": 100.0,
                        },
                    ),
                    Command.create(
                        {
                            "product_id": cls.product_b.id,
                            "product_qty": 2,
                            "price_unit": 7.0,
                        },
                    ),
                ],
            },
        )
        cls.two_line_order.action_confirm()

    def _draft_bill(self, lines):
        return self.env["account.move"].create(
            {
                "move_type": "in_invoice",
                "partner_id": self.partner_a.id,
                "invoice_date": self.order.date_order.date(),
                "invoice_line_ids": [Command.create(vals) for vals in lines],
            },
        )

    def _auto_complete(self, bill, order=None):
        bill.purchase_id = order or self.order
        bill._onchange_purchase_auto_complete()
        return bill.invoice_line_ids.filtered(
            lambda line: line.display_type == "product",
        )

    def test_matching_line_is_linked_instead_of_duplicated(self):
        bill = self._draft_bill(
            [{"product_id": self.product_a.id, "quantity": 5, "price_unit": 100.0}],
        )

        lines = self._auto_complete(bill)

        self.assertEqual(
            len(lines),
            1,
            "the line the buyer already typed is the one that gets linked",
        )
        self.assertEqual(lines.purchase_line_ids, self.order.line_ids)

    def test_empty_bill_still_receives_every_order_line(self):
        bill = self._draft_bill([])

        lines = self._auto_complete(bill, self.two_line_order)

        self.assertEqual(
            len(lines),
            2,
            "with nothing to match against, Auto-Complete still fills the bill",
        )
        self.assertEqual(lines.purchase_line_ids, self.two_line_order.line_ids)

    def test_fully_linked_bill_receives_the_order_lines_it_lacks(self):
        bill = self._draft_bill(
            [{"product_id": self.product_a.id, "quantity": 5, "price_unit": 100.0}],
        )
        bill.invoice_line_ids.purchase_line_ids = self.two_line_order.line_ids[0]

        lines = self._auto_complete(bill, self.two_line_order)

        self.assertEqual(
            len(lines),
            2,
            "billing a PO in two goes still works: the missing line comes in",
        )
        self.assertEqual(lines.purchase_line_ids, self.two_line_order.line_ids)

    def test_no_line_is_invented_when_a_bill_line_stays_unmatched(self):
        bill = self._draft_bill(
            [{"product_id": self.product_b.id, "quantity": 1, "price_unit": 7.0}],
        )

        lines = self._auto_complete(bill)

        self.assertEqual(
            len(lines),
            1,
            "the vendor billed product_b and nothing else; we do not add product_a",
        )
        self.assertFalse(lines.purchase_line_ids)

    def test_closest_candidate_wins_when_several_match(self):
        bill = self._draft_bill(
            [
                {"product_id": self.product_a.id, "quantity": 1, "price_unit": 100.0},
                {"product_id": self.product_a.id, "quantity": 5, "price_unit": 100.0},
            ],
        )

        lines = self._auto_complete(bill)

        self.assertEqual(len(lines), 2, "no line is created, both were already there")
        matched = lines.filtered("purchase_line_ids")
        self.assertEqual(len(matched), 1)
        self.assertEqual(
            matched.quantity,
            5,
            "the PO line asks for 5; the bill line of 5 is the better match",
        )

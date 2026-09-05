from odoo import Command
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("-at_install", "post_install")
class TestPurchaseLinePriceTracking(AccountTestInvoicingCommon):
    """Changing the agreed price of a confirmed order must leave a trace.

    Quantity changes have been logged for a long time
    (`_get_fields_tracked_qty` -> `_post_batched_quantity_changes`), but the
    unit price left none at all: `purchase.order` tracks `state`, `partner_id`,
    `user_id`, `locked`, `acknowledged`, `sent` and `printed_before`, and no
    amount. So renegotiating a confirmed order was invisible in the chatter.
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
                            "name": cls.product_a.name,
                            "product_id": cls.product_a.id,
                            "product_qty": 2.0,
                            "price_unit": 100.0,
                            "tax_ids": [Command.clear()],
                        },
                    ),
                    Command.create(
                        {
                            "name": cls.product_b.name,
                            "product_id": cls.product_b.id,
                            "product_qty": 5.0,
                            "price_unit": 20.0,
                            "tax_ids": [Command.clear()],
                        },
                    ),
                ],
            },
        )
        cls.line_a, cls.line_b = cls.order.line_ids

    def _new_messages(self, before):
        return self.order.message_ids - before

    def test_a_price_change_on_a_confirmed_order_is_logged(self):
        self.order.action_confirm()
        before = self.order.message_ids

        self.line_a.price_unit = 130.0

        messages = self._new_messages(before)
        self.assertEqual(len(messages), 1, "one note, on the order")
        body = messages.body
        self.assertIn("100.00", body)
        self.assertIn("130.00", body)
        self.assertIn(self.product_a.display_name, body)

    def test_a_price_change_on_a_draft_order_is_not_logged(self):
        before = self.order.message_ids

        self.line_a.price_unit = 130.0

        self.assertFalse(
            self._new_messages(before),
            "negotiating a draft RFQ is the normal case, not an event",
        )

    def test_writing_the_same_price_logs_nothing(self):
        self.order.action_confirm()
        before = self.order.message_ids

        self.line_a.price_unit = 100.0

        self.assertFalse(self._new_messages(before))

    def test_several_lines_repriced_at_once_give_one_note(self):
        self.order.action_confirm()
        before = self.order.message_ids

        self.order.line_ids.write({"price_unit": 55.0})

        messages = self._new_messages(before)
        self.assertEqual(
            len(messages),
            1,
            "the order batches its line changes into a single note, as it "
            "already does for quantities",
        )
        self.assertIn(self.product_a.display_name, messages.body)
        self.assertIn(self.product_b.display_name, messages.body)

    def test_quantity_and_price_changed_together_are_both_reported(self):
        self.order.action_confirm()
        before = self.order.message_ids

        self.line_a.write({"product_qty": 7.0, "price_unit": 130.0})

        bodies = " ".join(self._new_messages(before).mapped("body"))
        self.assertIn("130.00", bodies, "the price change must be reported")
        self.assertIn("7.0", bodies, "the quantity change must still be reported")

    def test_the_quantity_note_is_unchanged_when_only_the_quantity_moves(self):
        self.order.action_confirm()
        before = self.order.message_ids

        self.line_a.product_qty = 7.0

        messages = self._new_messages(before)
        self.assertEqual(len(messages), 1)
        self.assertIn("ordered quantity", messages.body.lower())

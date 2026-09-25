from odoo.tests import TransactionCase, tagged

from odoo.addons.trade.tools import direction_of


@tagged("post_install", "-at_install")
class TestOrderDocumentMatchGuard(TransactionCase):
    """`mixin.order.document.match` ships unusable defaults for
    `_order_table`/`_direction` -- a concrete model that forgets to
    override either must fail loudly, not silently build a broken query."""

    def test_missing_direction_raises(self):
        mixin = self.env["mixin.order.document.match"]
        with self.assertRaises(NotImplementedError):
            direction_of(mixin)

    def test_missing_order_table_raises(self):
        mixin = self.env["mixin.order.document.match"]
        with self.assertRaises(NotImplementedError):
            mixin._get_order_table()

    def test_concrete_consumers_still_resolve(self):
        for model in ("sale.invoice.match", "purchase.bill.match"):
            with self.subTest(model=model):
                record = self.env[model]
                self.assertTrue(direction_of(record).move_types)
                self.assertTrue(record._get_order_table())

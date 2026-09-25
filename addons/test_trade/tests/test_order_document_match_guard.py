from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestOrderDocumentMatchGuard(TransactionCase):
    """`mixin.order.document.match` ships unusable defaults for
    `_order_table`/`_move_types` -- a concrete model that forgets to
    override either must fail loudly, not silently build a broken query."""

    def test_missing_move_types_raises(self):
        mixin = self.env["mixin.order.document.match"]
        with self.assertRaises(NotImplementedError):
            mixin._get_move_types()

    def test_missing_order_table_raises(self):
        mixin = self.env["mixin.order.document.match"]
        with self.assertRaises(NotImplementedError):
            mixin._get_order_table()

    def test_concrete_consumers_still_resolve(self):
        for model in ("sale.invoice.match", "purchase.bill.match"):
            with self.subTest(model=model):
                record = self.env[model]
                self.assertTrue(record._get_move_types())
                self.assertTrue(record._get_order_table())

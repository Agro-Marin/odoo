from odoo.tests.common import TransactionCase


class BaseOrderTestCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "BO Partner"})
        cls.product = cls.env["product.product"].create(
            {
                "name": "BO Product",
                "list_price": 100.0,
            }
        )

    def _make_order(self, **kw):
        vals = {"partner_id": self.partner.id}
        vals.update(kw)
        return self.env["base.order.test"].create(vals)

    def _make_line(self, order=None, **kw):
        order = order or self._make_order()
        # `name` has no compute until Task 7; supply a default so callers that
        # don't care about the description can create lines freely.
        vals = {
            "order_id": order.id,
            "product_id": self.product.id,
            "name": "Test line",
        }
        vals.update(kw)
        return self.env["base.order.test.line"].create(vals)

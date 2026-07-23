# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSaleService(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.SOL = cls.env["sale.order.line"]
        cls.partner = cls.env["res.partner"].create({"name": "Client"})
        cls.service = cls.env["product.product"].create(
            {"name": "Consulting", "type": "service"}
        )
        cls.good = cls.env["product.product"].create(
            {"name": "Widget", "type": "consu"}
        )
        cls.order = cls.env["sale.order"].create({"partner_id": cls.partner.id})

    def _line(self, product):
        return self.SOL.create({"order_id": self.order.id, "product_id": product.id})

    def test_is_service_true_for_service_product(self):
        """A line for a service product is flagged as a service."""
        self.assertTrue(self._line(self.service).is_service)

    def test_is_service_false_for_consumable_product(self):
        """A line for a consumable product is not flagged as a service."""
        self.assertFalse(self._line(self.good).is_service)

    def test_domain_default_filters_service_expense_and_state(self):
        """The default service domain filters service, non-expense, done lines."""
        self.assertEqual(
            self.SOL._domain_sale_line_service(),
            [
                ("is_service", "=", True),
                ("is_expense", "=", False),
                ("state", "=", "done"),
            ],
        )

    def test_domain_can_drop_expense_leaf(self):
        """Disabling the expense check removes only that leaf."""
        domain = self.SOL._domain_sale_line_service(check_is_expense=False)
        self.assertNotIn(("is_expense", "=", False), domain)
        self.assertIn(("is_service", "=", True), domain)
        self.assertIn(("state", "=", "done"), domain)

    def test_domain_can_drop_state_leaf(self):
        """Disabling the state check removes only that leaf."""
        domain = self.SOL._domain_sale_line_service(check_state=False)
        self.assertNotIn(("state", "=", "done"), domain)
        self.assertIn(("is_service", "=", True), domain)
        self.assertIn(("is_expense", "=", False), domain)

    def test_additional_name_prefixes_price_for_grouped_services(self):
        """Grouped service lines expose their unit price in the extra name."""
        line_a = self._line(self.service)
        line_b = self._line(self.service)
        lines = line_a + line_b
        names = lines.with_context(with_price_unit=True)._additional_name_per_id()
        self.assertTrue(names[line_a.id].startswith("-"))
        self.assertTrue(names[line_b.id].startswith("-"))

    def test_name_search_returns_service_lines(self):
        """The service-scoped name_search returns matching service lines."""
        line = self._line(self.service)
        result = self.SOL.name_search(
            domain=[("is_service", "=", True)], operator="ilike", limit=10
        )
        self.assertIn(line.id, [res[0] for res in result])

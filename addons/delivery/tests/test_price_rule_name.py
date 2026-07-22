"""Tests for the human-readable delivery price-rule label."""

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPriceRuleName(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        product = cls.env["product.product"].create(
            {"name": "Delivery cost", "type": "service"}
        )
        cls.carrier = cls.env["delivery.carrier"].create(
            {
                "name": "PR name carrier",
                "delivery_type": "base_on_rule",
                "product_id": product.id,
            }
        )

    def _rule(self, **vals):
        base = {
            "carrier_id": self.carrier.id,
            "variable": "weight",
            "operator": "<=",
            "max_value": 10.0,
            "variable_factor": "weight",
        }
        base.update(vals)
        return self.env["delivery.price.rule"].create(base)

    def test_name_fixed_price_only(self):
        """A base price without a per-unit price reads as a fixed price."""
        rule = self._rule(list_base_price=5.0, list_price=0.0)
        self.assertIn("fixed price", rule.name)
        self.assertNotIn("plus", rule.name)

    def test_name_variable_only(self):
        """A per-unit price without a base reads as 'times <factor>'."""
        rule = self._rule(list_base_price=0.0, list_price=2.0)
        self.assertIn("times weight", rule.name)
        self.assertNotIn("fixed price", rule.name)

    def test_name_base_plus_variable(self):
        """Both prices read as a fixed price plus a per-unit term."""
        rule = self._rule(list_base_price=5.0, list_price=2.0)
        self.assertIn("fixed price", rule.name)
        self.assertIn("plus", rule.name)
        self.assertIn("times weight", rule.name)

    def test_name_carries_condition(self):
        """The label starts with the rule's if-condition."""
        rule = self._rule(list_base_price=5.0, operator=">=", max_value=3.0)
        self.assertIn("if weight >= 3.00 then", rule.name)

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
        """The label starts with the rule's if-condition, unit included."""
        rule = self._rule(list_base_price=5.0, operator=">=", max_value=3.0)
        self.assertIn(
            "if weight >= 3.00 %s then" % self.carrier.weight_uom_name, rule.name
        )

    def test_name_carries_the_volume_unit(self):
        """A volume rule reads in the volume unit, not the weight one."""
        rule = self._rule(variable="volume", list_base_price=5.0)
        self.assertIn(
            "if volume <= 10.00 %s then" % self.carrier.volume_uom_name, rule.name
        )

    def test_name_carries_both_units_for_weight_times_volume(self):
        """A weight * volume rule spells out both units."""
        rule = self._rule(variable="wv", list_base_price=5.0)
        self.assertIn(
            "if wv <= 10.00 %s * %s then"
            % (self.carrier.weight_uom_name, self.carrier.volume_uom_name),
            rule.name,
        )

    def test_name_carries_the_currency_for_a_price_rule(self):
        """A price rule reads in the carrier's currency."""
        rule = self._rule(variable="price", list_base_price=5.0)
        self.assertIn(
            "if price <= 10.00 %s then" % self.carrier.currency_id.symbol, rule.name
        )

    def test_name_omits_the_unit_when_the_variable_has_none(self):
        """A quantity rule has no unit to show, and must not print a stand-in."""
        rule = self._rule(variable="quantity", list_base_price=5.0)
        self.assertIn("if quantity <= 10.00 then", rule.name)
        self.assertNotIn("False", rule.name)

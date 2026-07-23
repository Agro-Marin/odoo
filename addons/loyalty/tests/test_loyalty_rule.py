# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.exceptions import ValidationError
from odoo.fields import Command
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestLoyaltyRule(TransactionCase):
    """loyalty.rule code/mode interplay, code uniqueness and product domain."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.program = cls.env["loyalty.program"].create(
            {
                "name": "Promo",
                "program_type": "promo_code",
                "rule_ids": [Command.create({"code": "RULEA", "minimum_amount": 0})],
            }
        )
        cls.rule = cls.program.rule_ids

    def test_code_implies_with_code_mode(self):
        """A rule created with a code is in with_code mode."""
        self.assertEqual(self.rule.mode, "with_code")

    def test_clearing_code_switches_to_auto(self):
        """Clearing the code flips the rule to auto mode."""
        self.rule.code = False
        self.assertEqual(self.rule.mode, "auto")

    def test_duplicate_code_is_rejected(self):
        """Two active rules cannot share a promo code."""
        with self.assertRaises(ValidationError):
            self.env["loyalty.program"].create(
                {
                    "name": "Promo dup",
                    "program_type": "promo_code",
                    "rule_ids": [
                        Command.create({"code": "RULEA", "minimum_amount": 0})
                    ],
                }
            )

    def test_get_valid_products_honours_product_ids(self):
        """_get_valid_products resolves the rule's configured products."""
        product = self.env["product.product"].create(
            {"name": "Rule Product", "type": "consu"}
        )
        self.rule.product_ids = [Command.link(product.id)]
        self.assertIn(product, self.rule._get_valid_products())

from odoo.fields import Command
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPurchaseTaxUsage(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.vendor = cls.env["res.partner"].create({"name": "Tax vendor"})
        cls.product = cls.env["product.product"].create(
            {
                "name": "Taxed part",
                "type": "consu",
                "purchase_ok": True,
            }
        )

    def _tax(self, name, amount=16):
        return self.env["account.tax"].create({"name": name, "amount": amount})

    def _order_with(self, tax):
        return self.env["purchase.order"].create(
            {
                "partner_id": self.vendor.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.product.id,
                            "product_qty": 1,
                            "tax_ids": [Command.set(tax.ids)],
                        }
                    )
                ],
            }
        )

    def test_tax_on_a_purchase_line_counts_as_used(self):
        tax = self._tax("Purchase VAT")
        self._order_with(tax)
        tax.invalidate_recordset(["is_used"])
        self.assertTrue(tax.is_used)

    def test_tax_nobody_references_is_free(self):
        tax = self._tax("Unused VAT", amount=8)
        tax.invalidate_recordset(["is_used"])
        self.assertFalse(tax.is_used)

    def test_it_reports_only_the_referenced_taxes(self):
        used = self._tax("Referenced")
        unused = self._tax("Not referenced", amount=4)
        self._order_with(used)
        result = self.env["account.tax"]._get_used_tax_ids({used.id, unused.id})
        self.assertIn(used.id, result)
        self.assertNotIn(unused.id, result)

    def test_it_leaves_the_candidate_set_alone(self):
        """Every override in the chain still needs the full set of candidates.

        They used to narrow it in place with `-=`, so each link silently shrank
        what the next one was given.
        """
        used = self._tax("Referenced too")
        unused = self._tax("Still not referenced", amount=6)
        self._order_with(used)
        candidates = {used.id, unused.id}
        self.env["account.tax"]._get_used_tax_ids(candidates)
        self.assertEqual(candidates, {used.id, unused.id})

    def test_with_no_candidates_returns_nothing(self):
        self.assertFalse(self.env["account.tax"]._get_used_tax_ids(set()))

    def test_tax_stays_used_after_the_order_is_cancelled(self):
        tax = self._tax("Cancelled VAT")
        order = self._order_with(tax)
        order.action_cancel()
        tax.invalidate_recordset(["is_used"])
        self.assertTrue(tax.is_used)

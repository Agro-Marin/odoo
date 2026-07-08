from odoo import Command
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestMarinAccountMoveLineFixes(AccountTestInvoicingCommon):
    """Regression tests for fork fixes in account/models/account_move_line.py."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.analytic_plan = cls.env["account.analytic.plan"].create(
            {"name": "Regression Plan"}
        )
        cls.aa_1, cls.aa_2 = cls.env["account.analytic.account"].create(
            [
                {"name": "AA 60", "plan_id": cls.analytic_plan.id},
                {"name": "AA 40", "plan_id": cls.analytic_plan.id},
            ]
        )

    def test_discount_allocation_analytic_distribution_is_weighted(self):
        """The generated discount line must mirror the product line's analytic split
        (60/40), not collapse every account to an even share (50/50)."""
        discount_account = self.company_data["default_account_expense"].copy()
        self.company_data[
            "company"
        ].account_discount_expense_allocation_id = discount_account

        distribution = {str(self.aa_1.id): 60.0, str(self.aa_2.id): 40.0}
        invoice = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": self.partner_a.id,
                "invoice_line_ids": [
                    Command.create(
                        {
                            "product_id": self.product_a.id,
                            "quantity": 1,
                            "discount": 5,
                            "analytic_distribution": distribution,
                        }
                    ),
                ],
            }
        )

        discount_lines = invoice.line_ids.filtered(
            lambda l: l.display_type == "discount"
        )
        self.assertTrue(discount_lines, "discount allocation lines should be generated")
        for line in discount_lines:
            self.assertEqual(
                {k: round(v, 2) for k, v in (line.analytic_distribution or {}).items()},
                distribution,
                "discount line analytic distribution must be weighted 60/40, not 50/50",
            )

    def test_term_key_recomputes_on_discount_date_change(self):
        """term_key embeds discount_date, so changing discount_date must invalidate it
        (previously it only depended on date_maturity and went stale)."""
        invoice = self.init_invoice(
            "out_invoice",
            partner=self.partner_a,
            products=self.product_a,
            post=False,
        )
        term_line = invoice.line_ids.filtered(
            lambda l: l.display_type == "payment_term"
        )
        term_line.ensure_one()

        before = term_line.term_key
        term_line.discount_date = "2099-01-01"
        after = term_line.term_key

        self.assertNotEqual(
            before, after, "term_key must refresh when discount_date changes"
        )
        self.assertEqual(after["discount_date"], term_line.discount_date)

    def test_hash_guard_covers_balance(self):
        """The inalterable-hash guard checks debit/credit, but those are computed
        from the writable `balance`. A direct `balance` write must be blocked too,
        otherwise it silently rewrites the hashed values (only caught later by the
        integrity report). Legitimate edits must still go through."""
        self.company_data["default_journal_sale"].restrict_mode_hash_table = True
        move = self.init_invoice(
            "out_invoice", self.partner_a, "2023-01-01", amounts=[1000.0], post=True
        )
        self.assertTrue(move.inalterable_hash)
        product_line = move.line_ids.filtered(lambda l: l.display_type == "product")

        with self.assertRaises(UserError):
            product_line.write({"balance": product_line.balance + 10.0})
        with self.assertRaises(UserError):
            product_line.write({"debit": product_line.debit + 10.0})

        # No corruption occurred and the hash still verifies.
        move.invalidate_recordset()
        results = move.company_id._check_hash_integrity()["results"]
        self.assertFalse(
            any("corrupted" in (r.get("msg_cover") or "").lower() for r in results)
        )

        # Allowed edits (non-hashed field, or a no-op same-value write) must not be
        # rejected by the change-gated guard.
        move.write({"ref": "still editable"})
        product_line.write({"name": product_line.name})

    def test_hash_guard_allows_balance_on_unhashed_move(self):
        """The balance guard must only bite on hashed moves."""
        move = self.init_invoice(
            "out_invoice", self.partner_a, "2023-01-01", amounts=[1000.0], post=False
        )
        self.assertFalse(move.inalterable_hash)
        product_line = move.line_ids.filtered(lambda l: l.display_type == "product")
        product_line.write({"balance": product_line.balance - 5.0})  # must not raise

    def test_parent_id_not_stale_on_sequence_change(self):
        """`parent_id` is a non-stored compute; without @api.depends it returned a
        stale cached section after a sibling's sequence changed."""
        move = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": self.partner_a.id,
                "invoice_line_ids": [
                    Command.create(
                        {"display_type": "line_section", "name": "SEC", "sequence": 5}
                    ),
                    Command.create(
                        {"name": "p", "quantity": 1, "price_unit": 10, "sequence": 10}
                    ),
                ],
            }
        )
        product_line = move.line_ids.filtered(lambda l: l.display_type == "product")
        section = move.line_ids.filtered(lambda l: l.display_type == "line_section")
        self.assertEqual(product_line.parent_id, section)  # populate the cache

        section.write({"sequence": 20})  # section now sorts after the product line
        self.assertFalse(
            product_line.parent_id,
            "parent_id must recompute automatically once the section moves after it",
        )

    def test_deductible_amount_boundary_tolerance(self):
        """Both bounds must use the same rounding tolerance as the vendor-bill check;
        a value a hair above 100 from float accumulation must not be rejected, while
        real out-of-range values still are."""
        move = self.init_invoice(
            "in_invoice", self.partner_a, "2023-01-01", amounts=[100.0], post=False
        )
        product_line = move.line_ids.filtered(lambda l: l.display_type == "product")[:1]
        # within rounding tolerance -> accepted
        product_line.deductible_amount = 100.000001
        product_line.deductible_amount = 0.0
        product_line.deductible_amount = 100.0
        # genuinely out of range -> rejected
        with self.assertRaises(ValidationError):
            product_line.deductible_amount = 100.01
        with self.assertRaises(ValidationError):
            product_line.deductible_amount = -0.01

    def test_line_compute_depends_completeness(self):
        """Registry-level guard: these computes read fields that were missing from
        their @api.depends, letting cached values go stale."""

        def deps(fname):
            field = self.env["account.move.line"]._fields[fname]
            return " ".join(self.env.registry.field_depends.get(field, ()))

        self.assertIn("display_type", deps("currency_id"))
        self.assertIn("company_id", deps("currency_id"))
        self.assertIn("partner_id", deps("translated_product_name"))
        self.assertIn("reversed_entry_id", deps("is_refund"))
        parent_field = self.env["account.move.line"]._fields["parent_id"]
        self.assertTrue(
            self.env.registry.field_depends.get(parent_field),
            "parent_id must declare dependencies",
        )

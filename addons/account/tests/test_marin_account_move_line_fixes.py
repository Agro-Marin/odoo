from datetime import date

from freezegun import freeze_time

from odoo import Command
from odoo.exceptions import UserError, ValidationError
from odoo.tests import Form, tagged
from odoo.tools import SQL

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
        """The discount allocation line mirrors the product line's weighted analytic split."""
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
        """term_key embeds discount_date, so changing discount_date must invalidate it."""
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
        """The inalterable-hash guard blocks a direct `balance` write, not just debit/credit."""
        self.company_data["default_journal_sale"].restrict_mode_hash_table = True
        move = self.init_invoice(
            "out_invoice", self.partner_a, "2023-01-01", amounts=[1000.0], post=True
        )
        self.assertTrue(move.inalterable_hash)
        product_line = move.line_ids.filtered(lambda l: l.display_type == "product")

        # debit/credit are computed from the writable `balance`, so an unguarded
        # balance write would rewrite the hashed values with nothing to catch it
        # until the integrity report runs.
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
        """`parent_id` must not serve a stale cached section after a sibling's sequence changes."""
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
        """Both deductible_amount bounds use the vendor-bill check's rounding tolerance."""
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

    def test_payment_date_timezone_consistency(self):
        """`payment_date` must resolve the same user-timezone today (context_today) in
        the Python compute, the `_search_payment_date` filter and `_field_to_sql`.
        """
        AML = self.env["account.move.line"]
        recv = self.company_data["default_account_receivable"]
        misc = self.company_data["default_account_revenue"]
        journal = self.company_data["default_journal_misc"]
        d_disc = date(2026, 7, 7)
        d_mat = date(2026, 7, 10)
        move = self.env["account.move"].create(
            {
                "move_type": "entry",
                "journal_id": journal.id,
                "date": date(2026, 7, 1),
                "line_ids": [
                    Command.create(
                        {
                            "account_id": recv.id,
                            "balance": 100.0,
                            "date_maturity": d_mat,
                        }
                    ),
                    Command.create({"account_id": misc.id, "balance": -100.0}),
                ],
            }
        )
        line = move.line_ids.filtered(lambda l: l.account_id == recv)
        line.discount_date = d_disc
        self.env.flush_all()

        # Frozen at 2026-07-08 03:00 UTC; a user in UTC-11 is still on 2026-07-07,
        # so date.today() (07-08) and context_today (07-07) deliberately disagree.
        with freeze_time("2026-07-08 03:00:00"):
            line_tz = line.with_context(tz="Pacific/Midway")
            aml_tz = AML.with_context(tz="Pacific/Midway")

            line_tz.invalidate_recordset(["payment_date"])
            py_val = line_tz.payment_date

            sql = aml_tz._field_to_sql("account_move_line", "payment_date")
            self.env.cr.execute(
                SQL("SELECT %s FROM account_move_line WHERE id = %s", sql, line.id)
            )
            sql_val = self.env.cr.fetchone()[0]

            # Both must resolve against the user's 2026-07-07: discount_date is still
            # valid, so payment_date is the discount_date, not the maturity date.
            self.assertEqual(
                py_val, d_disc, "compute must use user-tz today (discount_date valid)"
            )
            self.assertEqual(sql_val, d_disc, "SQL must use the same user-tz today")
            self.assertEqual(py_val, sql_val, "compute and SQL sort value must agree")

            # The filter must agree with the computed value too.
            found = aml_tz.search([("id", "=", line.id), ("payment_date", "=", d_disc)])
            self.assertIn(
                line, found, "search filter must agree with the computed payment_date"
            )

    def test_name_retranslates_on_partner_language_change(self):
        """An auto-derived line label re-translates when the invoice partner's language changes."""
        self.env["res.lang"]._activate_lang("fr_FR")
        partner_en = self.env["res.partner"].create(
            {"name": "EN partner", "lang": "en_US"}
        )
        partner_fr = self.env["res.partner"].create(
            {"name": "FR partner", "lang": "fr_FR"}
        )
        product = self.env["product.product"].create(
            {"name": "Gadget", "type": "consu"}
        )
        product.description_sale = "English description"
        product.with_context(lang="fr_FR").description_sale = "Description francaise"

        move_form = Form(
            self.env["account.move"].with_context(default_move_type="out_invoice")
        )
        move_form.partner_id = partner_en
        with move_form.invoice_line_ids.new() as line:
            line.product_id = product
        invoice = move_form.save()
        product_line = invoice.line_ids.filtered(lambda l: l.display_type == "product")
        self.assertIn("English description", product_line.name)

        with Form(invoice) as invoice_form:
            invoice_form.partner_id = partner_fr

        self.assertIn(
            "Description francaise",
            product_line.name,
            "line label must re-translate when the partner language changes",
        )
        self.assertNotIn("English description", product_line.name)

    def test_line_compute_depends_completeness(self):
        """Registry-level guard: each compute declares in @api.depends the fields it reads."""

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

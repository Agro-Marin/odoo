from odoo import Command
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestAccountTax(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_data_2 = cls.setup_other_company()

    @classmethod
    def default_env_context(cls):
        # OVERRIDE
        return {}

    def set_up_and_use_tax(self):

        self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "date": "2023-01-01",
                "invoice_line_ids": [
                    Command.create(
                        {
                            "name": "invoice_line",
                            "quantity": 1.0,
                            "price_unit": 100.0,
                            "tax_ids": [
                                Command.set(self.company_data["default_tax_sale"].ids)
                            ],
                        }
                    ),
                ],
            }
        )

        # Create two lines after creating the move so that those lines are not used in the move
        self.company_data["default_tax_sale"].write(
            {
                "invoice_repartition_line_ids": [
                    Command.create({"repartition_type": "tax", "factor_percent": 0.0}),
                ],
                "refund_repartition_line_ids": [
                    Command.create({"repartition_type": "tax", "factor_percent": 0.0}),
                ],
            }
        )

        self.flush_tracking()
        self.assertTrue(self.company_data["default_tax_sale"].is_used)

    def flush_tracking(self):
        """Force the creation of tracking values."""
        self.env.flush_all()
        self.cr.flush()

    def test_changing_tax_company(self):
        """Ensure you can't change the company of an account.tax if there are some journal entries"""

        # Avoid duplicate key value violates unique constraint "account_tax_name_company_uniq".
        self.company_data["default_tax_sale"].name = "test_changing_account_company"

        self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "date": "2019-01-01",
                "invoice_line_ids": [
                    (
                        0,
                        0,
                        {
                            "name": "invoice_line",
                            "quantity": 1.0,
                            "price_unit": 100.0,
                            "tax_ids": [
                                (6, 0, self.company_data["default_tax_sale"].ids)
                            ],
                        },
                    ),
                ],
            }
        )

        with self.assertRaises(UserError):
            self.company_data["default_tax_sale"].company_id = self.company_data_2[
                "company"
            ]

    def test_logging_of_tax_update_when_tax_is_used(self):
        """Modifications of a used tax should be logged."""

        self.set_up_and_use_tax()
        tax = self.company_data["default_tax_sale"]
        # `set_up_and_use_tax` adds two repartition lines to the (already used)
        # tax, which are correctly logged when they happen. Measure only the
        # messages produced by the scalar update below.
        messages_before = tax.message_ids

        tax.write(
            {
                "name": tax.name + " MODIFIED",
                "amount": 21,
                "amount_type": "fixed",
                "type_tax_use": "purchase",
                "price_include_override": "tax_included",
                "include_base_amount": True,
                "is_base_affected": False,
            }
        )
        self.flush_tracking()
        new_messages = tax.message_ids - messages_before
        self.assertEqual(
            len(new_messages),
            1,
            "Only 1 message should have been created when updating all the values.",
        )
        # There are 7 tracked values in account.tax and we update each of them, each on should be included in the message
        self.assertEqual(
            len(new_messages.tracking_value_ids),
            7,
            "The number of updated value should be 7.",
        )

    def test_logging_of_repartition_lines_addition_when_tax_is_used(self):
        """Adding repartition lines in a used tax should be logged."""

        self.set_up_and_use_tax()

        self.company_data["default_tax_sale"].write(
            {
                "invoice_repartition_line_ids": [
                    Command.create(
                        {"repartition_type": "tax", "factor_percent": -100.0}
                    ),
                ],
                "refund_repartition_line_ids": [
                    Command.create(
                        {"repartition_type": "tax", "factor_percent": -100.0}
                    ),
                ],
            }
        )
        self.flush_tracking()

        previews = self.company_data["default_tax_sale"].message_ids.mapped("preview")
        self.assertIn(
            "New Invoice repartition line 4: -100.0 (Factor Percent) None (Account) None (Tax Grids) False (Use in tax closing)",
            previews,
        )
        self.assertIn(
            "New Refund repartition line 4: -100.0 (Factor Percent) None (Account) None (Tax Grids) False (Use in tax closing)",
            previews,
        )

    def test_logging_of_repartition_lines_update_when_tax_is_used(self):
        """Updating repartition lines in a used tax should be logged."""

        self.set_up_and_use_tax()

        last_invoice_rep_line = self.company_data[
            "default_tax_sale"
        ].invoice_repartition_line_ids.filtered(
            lambda tax_rep: not tax_rep.factor_percent
        )
        last_refund_rep_line = self.company_data[
            "default_tax_sale"
        ].refund_repartition_line_ids.filtered(
            lambda tax_rep: not tax_rep.factor_percent
        )

        self.company_data["default_tax_sale"].write(
            {
                "invoice_repartition_line_ids": [
                    Command.update(
                        last_invoice_rep_line.id,
                        {
                            "factor_percent": -100,
                            "tag_ids": [Command.create({"name": "TaxTag12345"})],
                        },
                    ),
                ],
                "refund_repartition_line_ids": [
                    Command.update(
                        last_refund_rep_line.id,
                        {
                            "factor_percent": -100,
                            "account_id": self.company_data[
                                "default_account_tax_purchase"
                            ].id,
                        },
                    ),
                ],
            }
        )
        self.flush_tracking()

        previews = self.company_data["default_tax_sale"].message_ids.mapped("preview")
        self.assertIn(
            "Invoice repartition line 3: 0.0 -100.0 (Factor Percent) None ['TaxTag12345'] (Tax Grids)",
            previews,
        )
        self.assertIn(
            "Refund repartition line 3: 0.0 -100.0 (Factor Percent) None 131000 Tax Paid (Account) False True (Use in tax closing)",
            previews,
        )

    def test_logging_of_repartition_lines_reordering_when_tax_is_used(self):
        """Reordering repartition lines in a used tax should be logged."""

        self.set_up_and_use_tax()

        last_invoice_rep_line = self.company_data[
            "default_tax_sale"
        ].invoice_repartition_line_ids.filtered(
            lambda tax_rep: not tax_rep.factor_percent
        )
        last_refund_rep_line = self.company_data[
            "default_tax_sale"
        ].refund_repartition_line_ids.filtered(
            lambda tax_rep: not tax_rep.factor_percent
        )

        self.company_data["default_tax_sale"].write(
            {
                "invoice_repartition_line_ids": [
                    Command.update(last_invoice_rep_line.id, {"sequence": 0}),
                ],
                "refund_repartition_line_ids": [
                    Command.update(last_refund_rep_line.id, {"sequence": 0}),
                ],
            }
        )
        self.flush_tracking()

        previews = self.company_data["default_tax_sale"].message_ids.mapped("preview")
        self.assertIn(
            "Invoice repartition line 1: 100.0 0.0 (Factor Percent)", previews
        )
        self.assertIn(
            "Invoice repartition line 3: 0.0 100.0 (Factor Percent) None 251000 Tax Received (Account) False True (Use in tax closing)",
            previews,
        )

    def test_logging_of_repartition_lines_removal_when_tax_is_used(self):
        """Deleting repartition lines in a used tax should be logged."""

        self.set_up_and_use_tax()

        last_invoice_rep_line = self.company_data[
            "default_tax_sale"
        ].invoice_repartition_line_ids.sorted(key=lambda r: r.sequence)[-1]
        last_refund_rep_line = self.company_data[
            "default_tax_sale"
        ].refund_repartition_line_ids.sorted(key=lambda r: r.sequence)[-1]

        self.company_data["default_tax_sale"].write(
            {
                "invoice_repartition_line_ids": [
                    Command.delete(last_invoice_rep_line.id),
                ],
                "refund_repartition_line_ids": [
                    Command.delete(last_refund_rep_line.id),
                ],
            }
        )
        self.flush_tracking()

        previews = self.company_data["default_tax_sale"].message_ids.mapped("preview")
        self.assertIn(
            "Removed Invoice repartition line 3: 0.0 (Factor Percent) None (Account) None (Tax Grids) False (Use in tax closing)",
            previews,
        )
        self.assertIn(
            "Removed Refund repartition line 3: 0.0 (Factor Percent) None (Account) None (Tax Grids) False (Use in tax closing)",
            previews,
        )

    def test_tax_is_used_when_in_transactions(self):
        """Ensures that a tax is set to used when it is part of some transactions"""

        # Account.move is one type of transaction
        tax_invoice = self.env["account.tax"].create(
            {
                "name": "test_is_used_invoice",
                "amount": "100",
            }
        )

        self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "date": "2023-01-01",
                "invoice_line_ids": [
                    Command.create(
                        {
                            "name": "invoice_line",
                            "quantity": 1.0,
                            "price_unit": 100.0,
                            "tax_ids": [Command.set(tax_invoice.ids)],
                        }
                    ),
                ],
            }
        )
        tax_invoice.invalidate_model(fnames=["is_used"])
        self.assertTrue(tax_invoice.is_used)

        # Account.reconcile is another of transaction
        tax_reconciliation = self.env["account.tax"].create(
            {
                "name": "test_is_used_reconcilition",
                "amount": "100",
            }
        )
        self.env["account.reconcile.model"].create(
            {
                "name": "test_tax_is_used",
                "line_ids": [
                    Command.create(
                        {
                            "account_id": self.company_data[
                                "default_account_revenue"
                            ].id,
                            "tax_ids": [Command.set(tax_reconciliation.ids)],
                        }
                    )
                ],
            }
        )
        tax_reconciliation.invalidate_model(fnames=["is_used"])
        self.assertTrue(tax_reconciliation.is_used)

    def test_tax_no_duplicate_in_repartition_line(self):
        """Test that whenever a tax generate a second tax line
        the same tax is not applied to the tax line.
        """

        account_1 = self.company_data["default_account_tax_sale"].copy()
        account_2 = self.company_data["default_account_tax_sale"].copy()
        tax = self.env["account.tax"].create(
            {
                "name": "tax",
                "amount": 15.0,
                "include_base_amount": True,
                "invoice_repartition_line_ids": [
                    Command.create(
                        {
                            "repartition_type": "base",
                        }
                    ),
                    Command.create(
                        {
                            "factor_percent": 100,
                            "repartition_type": "tax",
                            "account_id": account_1.id,
                        }
                    ),
                    Command.create(
                        {
                            "factor_percent": -100,
                            "repartition_type": "tax",
                            "account_id": account_2.id,
                        }
                    ),
                ],
                "refund_repartition_line_ids": [
                    Command.create(
                        {
                            "repartition_type": "base",
                        }
                    ),
                    Command.create(
                        {
                            "factor_percent": 100,
                            "repartition_type": "tax",
                            "account_id": account_1.id,
                        }
                    ),
                    Command.create(
                        {
                            "factor_percent": -100,
                            "repartition_type": "tax",
                            "account_id": account_2.id,
                        }
                    ),
                ],
            }
        )

        invoice = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "date": "2019-01-01",
                "invoice_line_ids": [
                    Command.create(
                        {
                            "name": "invoice_line",
                            "quantity": 1.0,
                            "price_unit": 100.0,
                            "tax_ids": [Command.set(tax.ids)],
                        }
                    ),
                ],
            }
        )

        self.assertRecordValues(
            invoice,
            [
                {
                    "amount_untaxed": 100.0,
                    "amount_tax": 0.0,
                    "amount_total": 100.0,
                }
            ],
        )
        self.assertRecordValues(
            invoice.line_ids,
            [
                {
                    "display_type": "product",
                    "tax_ids": tax.ids,
                    "balance": -100.0,
                    "account_id": self.company_data["default_account_revenue"].id,
                },
                {
                    "display_type": "tax",
                    "tax_ids": [],
                    "balance": -15.0,
                    "account_id": account_1.id,
                },
                {
                    "display_type": "tax",
                    "tax_ids": [],
                    "balance": 15.0,
                    "account_id": account_2.id,
                },
                {
                    "display_type": "payment_term",
                    "tax_ids": [],
                    "balance": 100.0,
                    "account_id": self.company_data["default_account_receivable"].id,
                },
            ],
        )

    def test_display_alternative_taxes_field_follows_dependencies(self):
        """`display_alternative_taxes_field` reads `original_tax_ids` and
        `company_id.domestic_fiscal_position_id`, not only `fiscal_position_ids`.
        Its `@api.depends` must list them, otherwise the (non-stored) field stays
        stale when `original_tax_ids` changes during form editing.
        """
        tax = self.env["account.tax"].create(
            {"name": "alt-main", "amount": 21.0, "type_tax_use": "sale"}
        )
        domestic = self.env["account.tax"].create(
            {"name": "alt-domestic", "amount": 10.0, "type_tax_use": "sale"}
        )
        # No fiscal positions and nothing replaced yet -> field is falsy.
        self.assertFalse(tax.display_alternative_taxes_field)
        # Change ONLY the previously-undeclared dependency.
        tax.original_tax_ids = domestic
        # A missing dependency would leak the cached ``False`` here.
        self.assertTrue(tax.display_alternative_taxes_field)

    def test_repartition_lines_logging_survives_language_change(self):
        """Editing a used tax must never crash when the previously stored
        repartition snapshot was produced under a different language.

        Repartition snapshots used to be stored with *translated* dict keys, so
        diffing a snapshot taken under one language against another taken under a
        different language raised ``KeyError`` while merely saving the tax. Keys
        and values are now language-neutral tokens translated only at render time.
        """
        self.set_up_and_use_tax()
        tax = self.company_data["default_tax_sale"]

        # (a) Old translated-format snapshot vs new neutral-format snapshot:
        #     the migration path must not raise (it just can't produce a diff).
        old_translated = (
            "{('invoice', 1): {'Porcentaje de factor': 50.0, 'Cuenta': 'X', "
            "'Cuadros de impuestos': None, 'Usar en cierre de impuestos': 'Verdadero'}}"
        )
        new_neutral = (
            "{('invoice', 1): {'factor_percent': 100.0, 'account': 'X', "
            "'tax_grids': None, 'use_in_tax_closing': True}}"
        )
        # The following call must not raise (it used to raise KeyError).
        tax._message_log_repartition_lines(old_translated, new_neutral)

        # (b) Two neutral-format snapshots produce a correctly-labelled diff.
        tax.message_ids.unlink()
        old_neutral = (
            "{('invoice', 1): {'factor_percent': 50.0, 'account': 'X', "
            "'tax_grids': None, 'use_in_tax_closing': False}}"
        )
        tax._message_log_repartition_lines(old_neutral, new_neutral)
        joined = " ".join(tax.message_ids.mapped("preview"))
        self.assertIn("Factor Percent", joined)
        self.assertIn("50.0", joined)
        self.assertIn("100.0", joined)
        self.assertIn("Use in tax closing", joined)

    def test_compute_all_rounds_per_tax_base_under_round_globally(self):
        """Under 'round_globally' the raw base is a full-precision float; the
        per-tax 'base' returned by the legacy compute_all API must be rounded to
        the currency (like the totals), unless round_base=False is requested."""
        company = self.env.company
        company.tax_calculation_rounding_method = "round_globally"
        currency = company.currency_id
        tax = self.env["account.tax"].create(
            {
                "name": "incl 21",
                "amount_type": "percent",
                "amount": 21.0,
                "type_tax_use": "sale",
                "price_include_override": "tax_included",
                "company_id": company.id,
            }
        )
        res = tax.with_context(round_globally=True).compute_all(
            100.0, currency=currency, quantity=1.0
        )
        base = res["taxes"][0]["base"]
        self.assertEqual(
            base,
            currency.round(base),
            "per-tax base must be currency-rounded (round_base default True)",
        )
        # The raw, unrounded base is still available on explicit request.
        raw = tax.with_context(round_globally=True, round_base=False).compute_all(
            100.0, currency=currency, quantity=1.0
        )["taxes"][0]["base"]
        self.assertNotEqual(raw, currency.round(raw), "round_base=False keeps raw base")

    def test_division_tax_batch_over_100_percent_is_rejected(self):
        """A price-excluded division-tax batch summing to > 100% would leave a
        negative base and silently flip the tax sign; it must raise instead."""
        company = self.env.company
        currency = company.currency_id
        div_taxes = self.env["account.tax"].create(
            [
                {
                    "name": f"div60_{i}",
                    "amount_type": "division",
                    "amount": 60.0,
                    "type_tax_use": "sale",
                    "price_include_override": "tax_excluded",
                    "company_id": company.id,
                }
                for i in range(2)
            ]
        )
        with self.assertRaisesRegex(ValidationError, "cannot exceed 100"):
            div_taxes.compute_all(100.0, currency=currency, quantity=1.0)

        # A single valid price-excluded division tax still computes.
        result = div_taxes[0].compute_all(100.0, currency=currency, quantity=1.0)
        self.assertGreater(result["total_included"], 0.0)

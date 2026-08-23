import ast
import collections
import inspect
import textwrap

from odoo import Command
from odoo.tests import tagged
from odoo.tools import frozendict

from odoo.addons.account.models.account_move_sync import AccountMove
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestMarinAccountMoveSyncFixes(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["res.lang"]._activate_lang("fr_FR")
        cls.rounding_profit = cls.company_data["default_account_revenue"].copy()
        cls.rounding_loss = cls.company_data["default_account_expense"].copy()

    def _cash_rounding(self, strategy, rounding=0.05, with_accounts=True):
        vals = {
            "name": "R %s %s" % (strategy, rounding),
            "rounding": rounding,
            "strategy": strategy,
            "rounding_method": "HALF-UP",
        }
        if with_accounts:
            vals["profit_account_id"] = self.rounding_profit.id
            vals["loss_account_id"] = self.rounding_loss.id
        return self.env["account.cash.rounding"].create(vals)

    def _rounded_invoice(self, cash_rounding, price_unit, taxes):
        return self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": self.partner_a.id,
                "invoice_date": "2026-01-01",
                "invoice_cash_rounding_id": cash_rounding.id,
                "invoice_line_ids": [
                    Command.create(
                        {
                            "name": "p",
                            "quantity": 1,
                            "price_unit": price_unit,
                            "tax_ids": [Command.set(taxes.ids)],
                        }
                    )
                ],
            }
        )

    def _unbalanced_entry(self, env, first_line_name):
        expense = self.company_data["default_account_expense"]
        revenue = self.company_data["default_account_revenue"]
        return env["account.move"].create(
            {
                "move_type": "entry",
                "date": "2026-01-01",
                "line_ids": [
                    Command.create(
                        {
                            "name": first_line_name,
                            "account_id": expense.id,
                            "balance": 60.0,
                        }
                    ),
                    Command.create(
                        {
                            "name": "taxed",
                            "account_id": expense.id,
                            "balance": 40.0,
                            "tax_ids": [
                                Command.set(
                                    self.company_data["default_tax_purchase"].ids
                                )
                            ],
                        }
                    ),
                    Command.create(
                        {
                            "name": "counterpart",
                            "account_id": revenue.id,
                            "balance": -100.0,
                        }
                    ),
                ],
            }
        )

    def test_balancing_line_never_hijacks_a_line_by_name(self):
        marker_by_lang = {
            lang: self.env["account.move"]
            .with_context(lang=lang)
            .env._("Automatic Balancing Line")
            for lang in ("en_US", "fr_FR")
        }
        self.assertNotEqual(
            marker_by_lang["en_US"],
            marker_by_lang["fr_FR"],
            "this test is only meaningful while the marker is translated",
        )

        for lang in ("en_US", "fr_FR"):
            env = self.env(context=dict(self.env.context, lang=lang))
            for name in marker_by_lang.values():
                with self.subTest(acting_lang=lang, line_named=name):
                    move = self._unbalanced_entry(env, name)
                    entered = move.line_ids.filtered(
                        lambda line, name=name: (
                            line.display_type != "balancing" and line.name == name
                        )
                    )
                    self.assertEqual(
                        entered.balance,
                        60.0,
                        "a line the user named after the marker must keep its amount",
                    )
                    balancing = move.line_ids.filtered(
                        lambda line: line.display_type == "balancing"
                    )
                    self.assertEqual(len(balancing), 1)
                    tax_total = sum(
                        move.line_ids.filtered("tax_repartition_line_id").mapped(
                            "balance"
                        )
                    )
                    self.assertTrue(tax_total)
                    self.assertEqual(balancing.balance, -tax_total)
                    self.assertEqual(sum(move.line_ids.mapped("balance")), 0.0)

    def test_cash_rounding_line_is_written_in_place_for_both_strategies(self):
        tax = self.env["account.tax"].create(
            {
                "name": "sync 10%",
                "amount_type": "percent",
                "amount": 10.0,
                "type_tax_use": "sale",
                "company_id": self.env.company.id,
            }
        )
        for strategy in ("biggest_tax", "add_invoice_line"):
            with self.subTest(strategy=strategy):
                invoice = self._rounded_invoice(
                    self._cash_rounding(strategy), 11.11, tax
                )
                product_line = invoice.line_ids.filtered(
                    lambda line: line.display_type == "product"
                )
                previous_id = None
                recreated = 0
                for step in range(1, 21):
                    product_line.price_unit = 11.11 + 0.01 * step
                    rounding_line = invoice.line_ids.filtered(
                        lambda line: line.display_type == "rounding"
                    )
                    current_id = rounding_line.id if rounding_line else None
                    if current_id and previous_id and current_id != previous_id:
                        recreated += 1
                    previous_id = current_id
                self.assertEqual(
                    recreated,
                    0,
                    "the rounding line must be updated, not deleted and recreated",
                )

    def test_cash_rounding_applies_without_any_tax_line(self):
        for strategy in ("biggest_tax", "add_invoice_line"):
            with self.subTest(strategy=strategy):
                invoice = self._rounded_invoice(
                    self._cash_rounding(strategy, rounding=1.0),
                    100.4,
                    self.env["account.tax"],
                )
                self.assertEqual(invoice.amount_total, 100.0)

    def test_cash_rounding_without_accounts_does_not_raise(self):
        invoice = self._rounded_invoice(
            self._cash_rounding("biggest_tax", rounding=1.0, with_accounts=False),
            100.4,
            self.env["account.tax"],
        )
        self.assertEqual(invoice.amount_total, 100.4)

    def test_tracked_base_lines_match_the_tax_computation(self):
        invoice = self.env["account.move"].create(
            {
                "move_type": "in_invoice",
                "partner_id": self.partner_a.id,
                "invoice_date": "2026-01-01",
                "invoice_line_ids": [
                    Command.create(
                        {
                            "name": "x",
                            "quantity": 1,
                            "price_unit": 100.0,
                            "deductible_amount": 50,
                            "tax_ids": [
                                Command.set(
                                    self.company_data["default_tax_purchase"].ids
                                )
                            ],
                        }
                    )
                ],
            }
        )
        self.env["account.move.line"].create(
            [
                {
                    "move_id": invoice.id,
                    "display_type": "cogs",
                    "name": "cogs debit",
                    "account_id": self.company_data["default_account_expense"].id,
                    "balance": 70.0,
                },
                {
                    "move_id": invoice.id,
                    "display_type": "cogs",
                    "name": "cogs credit",
                    "account_id": self.company_data["default_account_revenue"].id,
                    "balance": -70.0,
                },
            ]
        )
        base_lines, _tax_lines = invoice._get_rounded_base_and_tax_lines()
        computed = self.env["account.move.line"].browse(
            [base_line["record"].id for base_line in base_lines]
        )
        self.assertEqual(
            set(invoice._get_tax_base_amls().ids),
            set(computed.ids),
            "the change detector and the tax computation must agree on base lines",
        )

    def _needed_values_key(self):
        move = self.env["account.move"].create(
            {"move_type": "entry", "date": "2026-01-01"}
        )
        return frozendict(
            {
                "move_id": move.id,
                "account_id": self.company_data["default_account_revenue"].id,
            }
        )

    def test_needed_values_merge_is_order_independent(self):
        key = self._needed_values_key()
        left = {"balance": 10.0, "amount_currency": 10.0}
        right = {
            "balance": -4.0,
            "amount_currency": -4.0,
            "discount_date": "2026-01-01",
        }
        forward = self.env["account.move"]._sync_dynamic_line_needed_values(
            [{key: left}, {key: right}]
        )
        backward = self.env["account.move"]._sync_dynamic_line_needed_values(
            [{key: right}, {key: left}]
        )
        self.assertEqual(set(forward[key]), set(backward[key]))
        self.assertEqual(
            set(forward[key]), {"balance", "amount_currency", "discount_date"}
        )
        self.assertEqual(forward[key]["balance"], backward[key]["balance"])

    def test_needed_values_merge_tolerates_a_missing_monetary_field(self):
        key = self._needed_values_key()
        merged = self.env["account.move"]._sync_dynamic_line_needed_values(
            [
                {key: {"balance": 10.0, "amount_currency": 10.0}},
                {key: {"balance": -4.0}},
            ]
        )
        self.assertEqual(merged[key]["balance"], 6.0)
        self.assertEqual(merged[key]["amount_currency"], 10.0)

    def test_sync_stack_runs_its_steps_in_list_order(self):
        container = {"records": self.env["account.move"]}
        stack, _update_containers = self.env["account.move"]._get_sync_stack(container)
        self.assertTrue(stack)
        self.assertFalse(
            [step for step in stack if isinstance(step, tuple)],
            "the stack is an ordered list of context managers, not (sequence, cm) pairs",
        )

    def test_sync_tax_lines_snapshots_only_what_it_compares(self):
        module = inspect.getmodule(AccountMove)
        tree = ast.parse(textwrap.dedent(inspect.getsource(module)))
        snapshotted = {
            constant.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and getattr(node.targets[0], "id", None) == "MOVE_TRACKED_FIELDS"
            for constant in ast.walk(node)
            if isinstance(constant, ast.Constant) and isinstance(constant.value, str)
        }
        self.assertTrue(snapshotted, "expected the snapshot to capture something")
        uses = collections.Counter(
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        )
        unread = sorted({field for field in snapshotted if uses[field] < 2})
        self.assertFalse(
            unread,
            "_sync_tax_lines snapshots %s and never compares them" % unread,
        )

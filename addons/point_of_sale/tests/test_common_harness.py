# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Self-tests for the `_run_test` checking harness in `common.py`.

The harness verifies journal entries by iterating the *actual* records and
matching each one into a list of declared expectations. That direction alone is
blind: when the actual recordset is empty, every declared expectation is skipped
and the test passes without asserting anything. These tests pin the reverse
direction -- that a declared expectation which nothing matched is a failure.
"""

from types import SimpleNamespace

import odoo

from odoo.addons.point_of_sale.tests.common import TestPoSCommon


@odoo.tests.tagged("post_install", "-at_install")
class TestPoSCommonHarness(TestPoSCommon):
    def _fake_session(self, statement_lines=(), bank_payments=()):
        """A stand-in for a pos.session exposing only what the checker reads.

        Building a real session would make the blinded case impossible to
        reproduce: the point is precisely that the checker sees empty recordsets
        while expectations are declared.
        """
        return SimpleNamespace(
            currency_id=self.env.company.currency_id,
            move_id=self.env["account.move"],
            statement_line_ids=list(statement_lines),
            bank_payment_ids=list(bank_payments),
        )

    def _fake_amount_record(self, amount):
        return SimpleNamespace(amount=amount, move_id=self.env["account.move"])

    def _fake_order(self, payments, is_invoiced=True):
        return SimpleNamespace(
            is_invoiced=is_invoiced,
            account_move=self.env["account.move"],
            payment_ids=list(payments),
        )

    def _fake_payment(self, payment_method, amount):
        return SimpleNamespace(
            payment_method_id=payment_method,
            amount=amount,
            account_move_id=self.env["account.move"],
        )

    def _session_expectations(self, cash_statement=(), bank_payments=()):
        # `session_journal_entry` is False so the checker skips it and only the
        # statement/payment matching under test is exercised.
        return {
            "session_journal_entry": False,
            "cash_statement": list(cash_statement),
            "bank_payments": list(bank_payments),
        }

    def test_blinded_cash_statement_is_caught(self):
        """A declared cash statement entry with no statement line must fail."""
        with self.assertRaises(AssertionError) as error:
            self._check_session_journal_entries(
                self._fake_session(),
                self._session_expectations(cash_statement=[((100,), False)]),
            )
        self.assertIn("cash statement line", str(error.exception))

    def test_blinded_bank_payments_is_caught(self):
        """A declared bank payment with no bank payment record must fail."""
        with self.assertRaises(AssertionError) as error:
            self._check_session_journal_entries(
                self._fake_session(),
                self._session_expectations(bank_payments=[((100,), False)]),
            )
        self.assertIn("bank payment", str(error.exception))

    def test_unexpected_actual_record_is_caught(self):
        """An actual record with no matching expectation must fail too."""
        with self.assertRaises(AssertionError):
            self._check_session_journal_entries(
                self._fake_session(statement_lines=[self._fake_amount_record(100)]),
                self._session_expectations(),
            )

    def test_amount_mismatch_is_caught(self):
        """Both directions fail when the amounts simply do not line up."""
        with self.assertRaises(AssertionError):
            self._check_session_journal_entries(
                self._fake_session(statement_lines=[self._fake_amount_record(100)]),
                self._session_expectations(cash_statement=[((50,), False)]),
            )

    def test_one_expectation_is_not_matched_twice(self):
        """Two identical statement lines need two declared entries, not one."""
        with self.assertRaises(AssertionError):
            self._check_session_journal_entries(
                self._fake_session(
                    statement_lines=[
                        self._fake_amount_record(100),
                        self._fake_amount_record(100),
                    ]
                ),
                self._session_expectations(cash_statement=[((100,), False)]),
            )

    def test_matching_records_and_expectations_pass(self):
        """Control case: one-to-one matches, including duplicates, must pass."""
        self._check_session_journal_entries(
            self._fake_session(
                statement_lines=[
                    self._fake_amount_record(100),
                    self._fake_amount_record(100),
                ],
                bank_payments=[self._fake_amount_record(50)],
            ),
            self._session_expectations(
                cash_statement=[((100,), False), ((100,), False)],
                bank_payments=[((50,), False)],
            ),
        )

    def test_blinded_invoice_payments_is_caught(self):
        """A declared invoice payment with no pos.payment must fail."""
        expected_values = {
            "00100-010-0001": {"payments": [((self.cash_pm1, 100), False)]}
        }
        with self.assertRaises(AssertionError) as error:
            self._check_invoice_journal_entries(
                self._fake_session(),
                {"00100-010-0001": self._fake_order([])},
                expected_values,
            )
        self.assertIn("invoice payment", str(error.exception))

    def test_matching_invoice_payments_pass(self):
        """Control case: pay later payments stay excluded from the expectations."""
        expected_values = {
            "00100-010-0001": {"payments": [((self.cash_pm1, 100), False)]}
        }
        self._check_invoice_journal_entries(
            self._fake_session(),
            {
                "00100-010-0001": self._fake_order(
                    [
                        self._fake_payment(self.cash_pm1, 100),
                        self._fake_payment(self.pay_later_pm, -100),
                    ]
                )
            },
            expected_values,
        )

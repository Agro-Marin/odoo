from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestAccountReconcileModel(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.counterpart = cls.company_data["default_account_expense"]

    def _model(self, name, **kw):
        kw.setdefault(
            "line_ids",
            [
                Command.create(
                    {
                        "account_id": self.counterpart.id,
                        "amount_type": "percentage",
                        "amount_string": "100",
                    }
                )
            ],
        )
        return self.env["account.reconcile.model"].create({"name": name, **kw})

    # -- label filter --------------------------------------------------------
    def test_match_regex_without_a_param_is_rejected(self):
        with self.assertRaises(ValidationError):
            self._model("no regex param", match_label="match_regex")

    def test_invalid_regex_is_rejected(self):
        with self.assertRaises(ValidationError):
            self._model("bad regex", match_label="match_regex", match_label_param="([")

    def test_contains_without_a_param_is_rejected(self):
        """Left unset the SQL predicate is NULL, so the model matches nothing at all."""
        for mode in ("contains", "not_contains"):
            with self.subTest(mode=mode), self.assertRaises(ValidationError):
                self._model(f"no param {mode}", match_label=mode)

    def test_a_label_param_alone_is_accepted(self):
        model = self._model("param only", match_label_param="ignored")
        self.assertFalse(model.match_label)

    # -- amount --------------------------------------------------------------
    def test_non_finite_amounts_are_rejected(self):
        """float() accepts these silently and they reach a journal item as inf/nan."""
        for bad in ("inf", "-inf", "Infinity", "nan", "1e400", "abc", "9" * 400):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                self._model(
                    f"bad amount {bad}",
                    line_ids=[
                        Command.create(
                            {
                                "account_id": self.counterpart.id,
                                "amount_type": "fixed",
                                "amount_string": bad,
                            }
                        )
                    ],
                )

    def test_either_decimal_separator_is_accepted(self):
        """The regex path has always read '1 234,56'; the typed path now agrees."""
        for text, expected in (
            ("1.5", 1.5),
            ("1,5", 1.5),
            ("1 234,56", 1234.56),
            ("1'234.56", 1234.56),
        ):
            with self.subTest(text=text):
                model = self._model(
                    f"sep {text}",
                    line_ids=[
                        Command.create(
                            {
                                "account_id": self.counterpart.id,
                                "amount_type": "fixed",
                                "amount_string": text,
                            }
                        )
                    ],
                )
                self.assertEqual(model.line_ids.amount, expected)

    def test_zero_amount_is_rejected(self):
        for amount_type in ("fixed", "percentage", "percentage_st_line"):
            with (
                self.subTest(amount_type=amount_type),
                self.assertRaises(ValidationError),
            ):
                self._model(
                    f"zero {amount_type}",
                    line_ids=[
                        Command.create(
                            {
                                "account_id": self.counterpart.id,
                                "amount_type": amount_type,
                                "amount_string": "0",
                            }
                        )
                    ],
                )

    def test_a_regex_line_does_not_need_a_numeric_amount(self):
        model = self._model(
            "regex line",
            line_ids=[
                Command.create(
                    {
                        "account_id": self.counterpart.id,
                        "amount_type": "regex",
                        "amount_string": r"BRT: ([\d,.]+)",
                    }
                )
            ],
        )
        self.assertEqual(model.line_ids.amount, 0.0)

    def test_amount_is_not_stored_so_it_cannot_drift(self):
        """A stored copy could be written to directly, leaving the effective amount
        disagreeing with the amount_string the form shows."""
        model = self._model(
            "no drift",
            line_ids=[
                Command.create(
                    {
                        "account_id": self.counterpart.id,
                        "amount_type": "fixed",
                        "amount_string": "10",
                    }
                )
            ],
        )
        self.assertFalse(
            self.env["account.reconcile.model.line"]._fields["amount"].store
        )
        model.line_ids.write({"amount": 0.0})
        model.line_ids.invalidate_recordset()
        self.assertEqual(model.line_ids.amount, 10.0)

    # -- proposability -------------------------------------------------------
    def test_a_journal_restricted_model_can_be_proposed(self):
        journal = self.company_data["default_journal_bank"]
        model = self._model(
            "journal only", match_journal_ids=[Command.set(journal.ids)]
        )
        self.assertTrue(
            model.can_be_proposed,
            "a journal restriction is a match condition, like a partner restriction",
        )

    def test_a_model_with_no_condition_is_not_proposed(self):
        self.assertFalse(self._model("no condition").can_be_proposed)

    # -- duplication ---------------------------------------------------------
    def test_copy_marks_the_duplicate(self):
        model = self._model("Bank Fees")
        self.assertEqual(model.copy().name, "Bank Fees (copy)")

    def test_copy_skips_names_already_taken(self):
        model = self._model("Taken")
        self._model("Taken (copy)")
        self.assertEqual(model.copy().name, "Taken (copy) (copy)")

    def test_copy_carries_the_marker_into_every_language(self):
        """The marker count used to be reconstructed by replaying a capped loop; past
        the cap the copy silently kept the source language's name in every language."""
        self.env["res.lang"]._activate_lang("fr_FR")
        model = self._model("Zeta")
        model.with_context(lang="fr_FR").name = "Zeta FR"
        for taken in range(1, 13):
            self._model("Zeta" + " (copy)" * taken)
        copied = model.copy()
        self.assertEqual(copied.with_context(lang="en_US").name.count("(copy)"), 13)
        self.assertTrue(copied.with_context(lang="fr_FR").name.startswith("Zeta FR"))

    # -- stat action ---------------------------------------------------------
    def test_reconcile_stat_action_is_scoped_to_the_model(self):
        model = self._model("stat")
        action = model.action_reconcile_stat()
        self.assertEqual(
            action["domain"], [("line_ids.reconcile_model_id", "=", model.id)]
        )

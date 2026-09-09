from odoo import Command
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestReconcileModelMatching(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.bank_journal = cls.company_data["default_journal_bank"]
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

    def _st_line(self, ref, amount=100.0, **kw):
        return self.env["account.bank.statement.line"].create(
            {
                "journal_id": self.bank_journal.id,
                "payment_ref": ref,
                "amount": amount,
                "date": "2026-08-01",
                **kw,
            }
        )

    def _offered(self, st_line):
        available = self.env[
            "account.reconcile.model"
        ].get_available_reconcile_model_per_statement_line(st_line.ids)
        return {entry["display_name"] for entry in available.get(st_line.id, [])}

    def test_control_plain_matching_works(self):
        self._model("CTL", match_label="contains", match_label_param="COFFEE")
        self.assertIn("CTL", self._offered(self._st_line("MONTHLY COFFEE BILL")))
        self.assertNotIn("CTL", self._offered(self._st_line("MONTHLY TEA BILL")))

    def test_control_an_active_auto_model_reconciles_on_create(self):
        line = self._st_line("OKPROBE PAYMENT", amount=400.0)
        self.env.flush_all()
        self._model(
            "OK",
            match_label="contains",
            match_label_param="OKPROBE",
            trigger="auto_reconcile",
        )
        line.invalidate_recordset()
        self.assertTrue(line.is_reconciled)

    def test_contains_is_a_literal_substring(self):
        self._model("PCT", match_label="contains", match_label_param="%")
        self.assertNotIn("PCT", self._offered(self._st_line("NOTHING RELEVANT")))

    def test_underscore_is_not_a_wildcard(self):
        self._model("US", match_label="contains", match_label_param="_NVOICE")
        self.assertNotIn("US", self._offered(self._st_line("INVOICE 2026")))

    def test_a_literal_percent_still_matches_itself(self):
        self._model("LIT", match_label="contains", match_label_param="5% FEE")
        self.assertIn("LIT", self._offered(self._st_line("MONTHLY 5% FEE CHARGED")))

    def test_transaction_detail_keys_are_not_matched(self):
        line = self._st_line(
            "PLAIN",
            transaction_details={"counterpartyNumber": "BE001", "communication": "hi"},
        )
        self._model("JK", match_label="contains", match_label_param="communication")
        self.assertNotIn("JK", self._offered(line))

    def test_transaction_detail_values_are_matched(self):
        line = self._st_line(
            "PLAIN",
            transaction_details={
                "communication": "ACME INVOICE",
                "nested": {"r": "XY"},
            },
        )
        self._model("JV", match_label="contains", match_label_param="ACME")
        self._model("JN", match_label="contains", match_label_param="XY")
        self.assertEqual({"JV", "JN"}, self._offered(line) & {"JV", "JN"})

    def test_narration_is_searched_by_every_path(self):
        line = self._st_line("PLAIN LABEL")
        line.move_id.narration = "<p>NARRATIONONLY marker</p>"
        self._model("NAR", match_label="contains", match_label_param="NARRATIONONLY")
        self.assertIn("NAR", self._offered(line))

    def test_an_amount_bound_set_after_creation_still_matches(self):
        model = self._model("BOUND")
        model.write({"match_amount": "lower"})
        self.assertIn("BOUND", self._offered(self._st_line("ANY", amount=-100.0)))

    def test_between_accepts_its_bounds_in_either_order(self):
        model = self._model("BTW")
        model.write(
            {
                "match_amount": "between",
                "match_amount_min": 500,
                "match_amount_max": 100,
            }
        )
        self.assertIn("BTW", self._offered(self._st_line("ANY", amount=300.0)))
        self.assertNotIn("BTW", self._offered(self._st_line("ANY", amount=900.0)))

    def test_renaming_a_model_does_not_reconcile(self):
        model = self._model(
            "REN",
            match_label="contains",
            match_label_param="RENPROBE",
            trigger="auto_reconcile",
        )
        lines = self.env["account.bank.statement.line"].create(
            [
                {
                    "journal_id": self.bank_journal.id,
                    "payment_ref": f"RENPROBE {index}",
                    "amount": 10.0 + index,
                    "date": "2026-08-01",
                }
                for index in range(5)
            ]
        )
        self.env.flush_all()
        self.assertFalse(any(lines.mapped("is_reconciled")))
        model.write({"name": "REN renamed"})
        lines.invalidate_recordset()
        self.assertFalse(any(lines.mapped("is_reconciled")))

    def test_changing_the_label_filter_reevaluates_the_backlog(self):
        model = self._model(
            "LBL",
            match_label="contains",
            match_label_param="NOMATCHYET",
            trigger="auto_reconcile",
        )
        line = self._st_line("LBLPROBE PAYMENT", amount=400.0)
        self.env.flush_all()
        self.assertFalse(line.is_reconciled)
        model.write({"match_label_param": "LBLPROBE"})
        line.invalidate_recordset()
        self.assertTrue(line.is_reconciled)

    def test_renaming_does_not_reevaluate_the_backlog(self):
        model = self._model(
            "NAMEONLY", match_label="contains", match_label_param="NAMEPROBE"
        )
        line = self._st_line("NAMEPROBE PAYMENT", amount=400.0)
        self.env.flush_all()
        model.write({"name": "NAMEONLY renamed", "next_activity_type_id": False})
        line.invalidate_recordset()
        self.assertFalse(line.is_reconciled)

    def test_archiving_a_model_does_not_reconcile(self):
        model = self._model(
            "ARCH",
            match_label="contains",
            match_label_param="ARCHPROBE",
            trigger="auto_reconcile",
        )
        line = self._st_line("ARCHPROBE PAYMENT", amount=500.0)
        self.env.flush_all()
        self.assertFalse(line.is_reconciled)
        model.action_archive()
        line.invalidate_recordset()
        self.assertFalse(line.is_reconciled)

    def test_creating_an_archived_model_does_not_reconcile(self):
        line = self._st_line("CAFPROBE PAYMENT", amount=400.0)
        self.env.flush_all()
        self._model(
            "CAF",
            active=False,
            match_label="contains",
            match_label_param="CAFPROBE",
            trigger="auto_reconcile",
        )
        line.invalidate_recordset()
        self.assertFalse(line.is_reconciled)

    def test_an_archived_model_is_not_offered(self):
        model = self._model("OFF", match_label="contains", match_label_param="OFFPROBE")
        line = self._st_line("OFFPROBE PAYMENT")
        self.assertIn("OFF", self._offered(line))
        model.action_archive()
        self.assertNotIn("OFF", self._offered(line))

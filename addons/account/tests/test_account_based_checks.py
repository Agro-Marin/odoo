from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestAccountBasedChecks(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.report = cls.env["account.report"].create(
            {"name": "Account-based checks report", "country_id": False}
        )
        cls.return_type = cls.env["account.return.type"].create(
            {
                "name": "Account-based checks return type",
                "report_id": cls.report.id,
                "deadline_start_date": "2019-01-01",
                "states_workflow": "generic_state_tax_report",
            }
        )
        cls.audit = cls.env["account.return"].create(
            {
                "name": "Audit 2019",
                "type_id": cls.return_type.id,
                "company_id": cls.env.company.id,
                "date_from": "2019-01-01",
                "date_to": "2019-12-31",
            }
        )
        cls.receivable = cls.company_data["default_account_receivable"]
        cls.payable = cls.company_data["default_account_payable"]

    def _template(self, domain):
        return self.env["account.return.check.template"].create(
            {
                "name": "Receivables reviewed",
                "code": "account_based_check",
                "type": "check",
                "model": "account.account",
                "domain": domain,
                "cycle": "regulatory_compliance",
                "return_type": self.return_type.id,
            }
        )

    def _set_status(self, account, status):
        return self.env["account.audit.account.status"].create(
            {
                "audit_id": self.audit.id,
                "account_id": account.id,
                "status": status,
            }
        )

    def _vals_of(self, code):
        """`_execute_template_checks` returns the check vals; it creates nothing."""
        vals = next(
            (
                vals
                for vals in self.audit._execute_template_checks([])
                if vals.get("code") == code
            ),
            None,
        )
        self.assertTrue(vals, f"the template {code!r} must produce a check")
        return vals

    def _result_of(self, template):
        return self._vals_of(template.code)["result"]

    def test_an_account_check_reports_the_least_advanced_status(self):
        """A set of accounts is only as far along as the one nobody has opened.

        Counting matching records is the wrong question for an account: an
        account is something a person reviews, and the audit already tracks how
        far that got. The check reports that instead.
        """
        template = self._template(
            "[('account_type', 'in', ('asset_receivable', 'liability_payable'))]"
        )
        self._set_status(self.receivable, "reviewed")
        self._set_status(self.payable, "todo")

        self.assertEqual(
            self._result_of(template),
            "todo",
            "one account still to review holds the whole check back",
        )

    def test_an_anomaly_outranks_everything(self):
        template = self._template("[('account_type', '=', 'asset_receivable')]")
        self._set_status(self.receivable, "anomaly")

        self.assertEqual(self._result_of(template), "anomaly")

    def test_accounts_nobody_stamped_read_as_reviewed(self):
        """No status means no entries to review, which is as good as reviewed.

        That is the same reading the audit uses when it seeds the statuses.
        """
        template = self._template("[('account_type', '=', 'asset_receivable')]")

        self.assertEqual(self._result_of(template), "reviewed")

    def test_a_record_counting_check_is_untouched(self):
        """The other models keep counting records; only accounts changed."""
        template = self.env["account.return.check.template"].create(
            {
                "name": "Entries in the period",
                "code": "entry_counting_check",
                "type": "check",
                "model": "account.move",
                "domain": "[]",
                "cycle": "regulatory_compliance",
                "return_type": self.return_type.id,
            }
        )
        self.init_invoice(
            "out_invoice", invoice_date="2019-06-01", amounts=[100.0], post=True
        )

        vals = self._vals_of(template.code)

        self.assertEqual(
            vals["result"], "anomaly", "entries in the period are still flagged"
        )
        self.assertGreaterEqual(vals["records_count"], 1)
        self.assertEqual(
            self.env["ir.model"].browse(vals["records_model"]).model, "account.move"
        )

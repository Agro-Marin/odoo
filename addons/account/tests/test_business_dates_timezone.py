from freezegun import freeze_time

from odoo import fields
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon

# 02:00 UTC is 20:00 of the previous day in America/Mexico_City (UTC-6).
# Every assertion below is about that window: the only one where a UTC clock
# and the accountant's calendar disagree about what day it is.
EVENING_IN_MEXICO = "2019-01-02 02:00:00"
LOCAL_DAY = fields.Date.to_date("2019-01-01")


@tagged("post_install", "-at_install")
class TestBusinessDatesTimezone(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.tz = "America/Mexico_City"

    @freeze_time(EVENING_IN_MEXICO)
    def test_an_invoice_due_today_is_not_overdue_in_the_evening(self):
        """At 20:00 in Mexico City it is still the day the invoice falls due.

        `fields.Date.today()` is UTC, so from 18:00 local onwards it already
        reports tomorrow and the follow-up report moves a customer into the
        overdue bucket a day early -- on the very day they still have to pay.
        """
        self.assertEqual(
            fields.Date.today(),
            fields.Date.to_date("2019-01-02"),
            "the test is only meaningful while UTC and Mexico City disagree",
        )
        aml_results = [{"date_maturity": LOCAL_DAY}]
        report = self.env["account.followup.report.handler"]

        self.assertFalse(
            report._filter_overdue_amls_from_results(aml_results),
            "an invoice due today is not overdue yet",
        )
        self.assertEqual(
            report._filter_due_amls_from_results(aml_results),
            aml_results,
            "it belongs in the due bucket, not the overdue one",
        )

    @freeze_time(EVENING_IN_MEXICO)
    def test_yesterdays_invoice_is_still_overdue(self):
        """The other direction: the fix must not stop reporting real arrears."""
        aml_results = [{"date_maturity": fields.Date.to_date("2018-12-31")}]
        report = self.env["account.followup.report.handler"]

        self.assertEqual(
            report._filter_overdue_amls_from_results(aml_results), aml_results
        )
        self.assertFalse(report._filter_due_amls_from_results(aml_results))

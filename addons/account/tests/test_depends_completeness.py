"""`account`'s computed fields must declare what they read.

Both fields here went stale for the rest of the transaction that changed their
input, and neither was visible to `depends_audit`: it examines only computes
that declare nothing, and both declared something.
"""

from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestAccountDependsCompleteness(AccountTestInvoicingCommon):
    def test_partner_credit_limit_flag_follows_the_limit(self):
        partner = self.env["res.partner"].create({"name": "Depends probe"})
        self.assertDependsComplete(
            partner,
            computed_fields=["use_partner_credit_limit"],
        )

    def test_audit_log_preview_follows_the_message_it_previews(self):
        message = self.env["mail.message"].create(
            {
                "model": "res.partner",
                "res_id": self.partner_a.id,
                "message_type": "notification",
                "subject": "Depends probe",
                "body": "<p>probe</p>",
            }
        )
        self.assertDependsComplete(
            message,
            computed_fields=["account_audit_log_preview"],
            probe_fields=["subject", "body", "message_type"],
        )

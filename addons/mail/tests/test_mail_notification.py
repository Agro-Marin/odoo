from odoo.tests import tagged

from odoo.addons.mail.tests.common import MailCommon

FAILURE_TYPE = "mail_email_invalid"


@tagged("mail_notification")
class TestMailNotificationFailureReason(MailCommon):
    """`format_failure_reason` reaches the user, so it speaks the user's language."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["res.lang"]._activate_lang("fr_FR")
        cls.env["ir.model.fields.selection"].search(
            [
                ("field_id.model", "=", "mail.notification"),
                ("field_id.name", "=", "failure_type"),
                ("value", "=", FAILURE_TYPE),
            ],
            limit=1,
        ).with_context(lang="fr_FR").name = "Adresse invalide"

    def test_failure_reason_is_translated(self):
        notification = self.env["mail.notification"].new(
            {"failure_type": FAILURE_TYPE, "notification_type": "email"}
        )
        self.assertEqual(
            notification.with_context(lang="fr_FR").format_failure_reason(),
            "Adresse invalide",
            "the label must come from the field's translated selection, not from "
            "its raw `selection` attribute",
        )

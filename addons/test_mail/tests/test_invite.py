from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.mail.tests.common import MailCommon


@tagged("mail_followers")
class TestInvite(MailCommon):
    @mute_logger("odoo.addons.mail.models.mail_mail")
    def test_invite_email(self):
        test_record = (
            self.env["mail.test.simple"]
            .with_context(self._test_context)
            .create({"name": "Test", "email_from": "ignasse@example.com"})
        )
        test_partner = (
            self.env["res.partner"]
            .with_context(self._test_context)
            .create({"name": "Valid Lelitre", "email": "valid.lelitre@agrolait.com"})
        )

        mail_invite = (
            self.env["mail.followers.edit"]
            .with_context(
                {
                    "default_res_model": "mail.test.simple",
                    "default_res_ids": [test_record.id],
                }
            )
            .with_user(self.user_employee)
            .create(
                {
                    "partner_ids": [
                        (4, test_partner.id),
                        (4, self.user_admin.partner_id.id),
                    ],
                    "notify": True,
                }
            )
        )
        with self.mock_mail_app(), self.mock_mail_gateway():
            mail_invite.edit_followers()

        # Check added followers and that notifications are sent.
        # Admin notification preference is inbox so the notification must be of inbox type
        # while partner_employee must receive it by email.
        self.assertEqual(
            test_record.message_partner_ids, test_partner | self.user_admin.partner_id
        )
        self.assertEqual(len(self._new_msgs), 1)
        self.assertEqual(len(self._mails), 1)
        self.assertSentEmail(self.partner_employee, [test_partner])
        self.assertNotSentEmail([self.partner_admin])
        self.assertNotified(
            self._new_msgs[0],
            [{"partner": self.partner_admin, "type": "inbox", "is_read": False}],
        )

        # Remove followers
        mail_remove = (
            self.env["mail.followers.edit"]
            .with_context(
                {
                    "default_res_model": "mail.test.simple",
                    "default_res_ids": [test_record.id],
                }
            )
            .with_user(self.user_employee)
            .create(
                {
                    "operation": "remove",
                    "partner_ids": [
                        (4, test_partner.id),
                        (4, self.user_admin.partner_id.id),
                    ],
                }
            )
        )

        with self.mock_mail_app(), self.mock_mail_gateway():
            mail_remove.edit_followers()

        # Check removed followers and that notifications are sent.
        self.assertEqual(test_record.message_partner_ids, self.env["res.partner"])

    def test_edit_followers_drops_stale_ids_and_refuses_an_empty_selection(self):
        Simple = self.env["mail.test.simple"].with_context(self._test_context)
        record, stale = Simple.create([{"name": "Kept"}, {"name": "Removed"}])
        stale_id = stale.id
        stale.unlink()
        partner = self.env["res.partner"].create({"name": "Follower"})
        Wizard = self.env["mail.followers.edit"].with_user(self.user_employee)

        wizard = Wizard.create(
            {
                "res_model": "mail.test.simple",
                "res_ids": str([record.id, stale_id]),
                "partner_ids": [(4, partner.id)],
            }
        )
        wizard.edit_followers()
        self.assertIn(partner, record.message_partner_ids)

        wizard = Wizard.create(
            {
                "res_model": "mail.test.simple",
                "res_ids": str([stale_id]),
                "partner_ids": [(4, partner.id)],
            }
        )
        with self.assertRaises(UserError):
            wizard.edit_followers()

    def test_edit_followers_message_names_the_operation(self):
        record = (
            self.env["mail.test.simple"]
            .with_context(self._test_context)
            .create({"name": "Named"})
        )
        partner = self.env["res.partner"].create({"name": "Follower"})
        Wizard = self.env["mail.followers.edit"].with_user(self.user_employee)
        add, remove = Wizard.create(
            [
                {
                    "res_model": "mail.test.simple",
                    "res_ids": str([record.id]),
                    "partner_ids": [(4, partner.id)],
                },
                {
                    "res_model": "mail.test.simple",
                    "res_ids": str([record.id]),
                    "partner_ids": [(4, partner.id)],
                    "operation": "remove",
                },
            ]
        )
        self.assertEqual(add.edit_followers()["params"]["message"], "Followers added")
        self.assertEqual(
            remove.edit_followers()["params"]["message"], "Followers removed"
        )
        self.assertEqual(
            (add | remove).edit_followers()["params"]["message"],
            "Followers updated",
        )

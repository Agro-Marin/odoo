from markupsafe import Markup

import odoo
from odoo.tools.misc import file_open

from odoo.addons.mail.tests.common_controllers import MailControllerAttachmentCommon


@odoo.tests.tagged("-at_install", "post_install", "mail_controller")
class TestDiscussAttachmentController(MailControllerAttachmentCommon):
    def test_attachment_allowed_upload_public_channel(self):
        channel = self.env["discuss.channel"].create(
            {"group_public_id": None, "name": "public channel"}
        )
        channel._add_members(guests=self.guest)
        channel = channel.with_context(guest=self.guest)
        self._execute_subtests_upload(
            channel,
            (
                (self.guest, True),
                (self.user_admin, True),
                (self.user_employee, True),
                (self.user_portal, True),
                (self.user_public, True),
            ),
        )

    def test_attachment_delete_linked_to_public_channel(self):
        channel = self.env["discuss.channel"].create(
            {"group_public_id": None, "name": "public channel"}
        )
        self._execute_subtests_delete(
            self.all_users, token=True, allowed=True, thread=channel
        )
        self._execute_subtests_delete(
            (self.user_admin, self.user_employee),
            token=False,
            allowed=True,
            thread=channel,
        )
        self._execute_subtests_delete(
            (self.guest, self.user_portal, self.user_public),
            token=False,
            allowed=False,
            thread=channel,
        )

    def test_attachment_delete_linked_to_private_channel(self):
        channel = self.env["discuss.channel"].create(
            {"name": "Private Channel", "channel_type": "group"}
        )
        self._execute_subtests_delete(
            self.all_users, token=True, allowed=True, thread=channel
        )
        self._execute_subtests_delete(
            self.user_admin, token=False, allowed=True, thread=channel
        )
        self._execute_subtests_delete(
            (self.guest, self.user_employee, self.user_portal, self.user_public),
            token=False,
            allowed=False,
            thread=channel,
        )

    def _post_with_attachment(self, channel, message_type):
        attachment = self.env["ir.attachment"].create(
            {
                "name": "sample attachment",
                "res_model": channel._name,
                "res_id": channel.id,
            }
        )
        message = channel.with_user(self.user_employee).message_post(
            body=Markup("<p>Have a look at this</p>"),
            attachment_ids=attachment.ids,
            message_type=message_type,
            subtype_xmlid="mail.mt_comment",
        )
        self.assertIn(attachment, message.attachment_ids)
        self.assertNotIn("o-mail-Message-edited", message.body)
        return attachment, message

    def test_attachment_delete_marks_the_message_as_edited(self):
        channel = self.env["discuss.channel"].create(
            {"group_public_id": None, "name": "public channel"}
        )
        channel._add_members(users=self.user_employee)
        attachment, message = self._post_with_attachment(channel, "comment")
        self._authenticate_pseudo_user(self.user_employee)
        self._remove_attachment(attachment, token=True)
        self.assertFalse(attachment.exists())
        self.assertIn(
            "o-mail-Message-edited",
            message.body,
            "removing an attachment leaves the same trace as editing the body",
        )

    def test_attachment_delete_leaves_uneditable_messages_alone(self):
        """A message whose content cannot be updated must still let go of its
        attachments: only the edited marker is skipped."""
        channel = self.env["discuss.channel"].create(
            {"group_public_id": None, "name": "public channel"}
        )
        channel._add_members(users=self.user_employee)
        attachment, message = self._post_with_attachment(channel, "notification")
        self._authenticate_pseudo_user(self.user_employee)
        self._remove_attachment(attachment, token=True)
        self.assertFalse(attachment.exists())
        self.assertNotIn("o-mail-Message-edited", message.body)

    def test_first_page_access_of_mail_attachment_pdf(self):
        attachments = []
        for pdf in (
            "mail/tests/discuss/files/test_AES.pdf",
            "mail/tests/discuss/files/test_unicode.pdf",
        ):
            with file_open(pdf, "rb") as file:
                attachments.append(
                    {
                        "name": pdf,
                        "raw": file.read(),
                        "mimetype": "application/pdf",
                    }
                )
        attachments = self.env["ir.attachment"].create(attachments)

        self.authenticate("admin", "admin")

        for attachment in attachments:
            ownership_token = attachment._get_ownership_token()
            url = f"/mail/attachment/pdf_first_page/{attachment.id}?access_token={ownership_token}"
            response = self.url_open(url)
            self.assertIn(response.status_code, [415, 200])

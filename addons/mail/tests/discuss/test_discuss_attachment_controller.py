from unittest.mock import patch

import odoo
from odoo.tests import JsonRpcException
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

    def test_attachment_delete_refusal_echoes_to_the_guest(self):
        channel = self.env["discuss.channel"].create(
            {"group_public_id": None, "name": "public channel"}
        )
        attachment = self.env["ir.attachment"].create(
            {"name": "sample", "res_model": channel._name, "res_id": channel.id}
        )
        self._authenticate_pseudo_user(self.guest)
        sent = []

        def spy_guest(records, notification_type, message, /, **kwargs):
            sent.append(("guest", records, notification_type, message))

        def spy_user(records, notification_type, message, /, **kwargs):
            sent.append(("user", records, notification_type, message))

        with (
            patch.object(type(self.env["mail.guest"]), "_bus_send", spy_guest),
            patch.object(type(self.env["res.users"]), "_bus_send", spy_user),
            self.assertRaises(JsonRpcException) as capture,
        ):
            self._remove_attachment(attachment, token=False)

        self.assertEqual(capture.exception.code, 404)
        self.assertEqual(
            [
                (who, records, notification_type)
                for who, records, notification_type, _ in sent
            ],
            [("guest", self.guest, "ir.attachment/delete")],
            "the echo belongs on the guest's bus, not the public user's",
        )
        self.assertEqual(sent[0][3], {"id": attachment.id})

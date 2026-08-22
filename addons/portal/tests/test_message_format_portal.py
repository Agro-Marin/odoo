from odoo.tests import common, tagged
from odoo.tools import mute_logger


@tagged("mail_message")
class TestMessageFormatPortal(common.TransactionCase):
    @mute_logger("odoo.models.unlink")
    def test_portal_message_format(self):

        partner = self.env["res.partner"].create({"name": "Partner"})
        message_no_subtype = self.env["mail.message"].create(
            [
                {
                    "model": "res.partner",
                    "res_id": partner.id,
                }
            ]
        )
        formatted_result = message_no_subtype.portal_message_format()
        self.assertFalse(formatted_result[0].get("is_message_subtype_note"))

        message_comment = self.env["mail.message"].create(
            [
                {
                    "model": "res.partner",
                    "res_id": partner.id,
                    "subtype_id": self.env["ir.model.data"]._xmlid_to_res_id(
                        "mail.mt_comment"
                    ),
                }
            ]
        )
        formatted_result = message_comment.portal_message_format()
        self.assertFalse(formatted_result[0].get("is_message_subtype_note"))

        message_note = self.env["mail.message"].create(
            [
                {
                    "model": "res.partner",
                    "res_id": partner.id,
                    "subtype_id": self.env["ir.model.data"]._xmlid_to_res_id(
                        "mail.mt_note"
                    ),
                }
            ]
        )
        formatted_result = message_note.portal_message_format()
        self.assertTrue(formatted_result[0].get("is_message_subtype_note"))

    def test_portal_message_format_without_author(self):
        message = self.env["mail.message"].create(
            {
                "model": "res.partner",
                "res_id": self.env.user.partner_id.id,
                "author_id": False,
                "body": "Hello",
            }
        )
        result = message.portal_message_format()
        self.assertEqual(result[0]["author_id"], False)

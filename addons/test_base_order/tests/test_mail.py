from odoo.tests import tagged

from .common import BaseOrderTestCase


@tagged("post_install", "-at_install")
class TestMail(BaseOrderTestCase):
    def test_rendering_context_has_subtitles(self):
        order = self._make_order()
        message = order.message_post(body="hello")

        ctx = order._notify_by_email_prepare_rendering_context(message)

        self.assertIn("subtitles", ctx)
        self.assertEqual(ctx["subtitles"], [order.name])

    def test_track_subtype_uses_hook_xmlid(self):
        order = self._make_order()
        order.state = "done"

        subtype = order._track_subtype({"state": "draft"})

        self.assertEqual(subtype, self.env.ref("mail.mt_note"))

    def test_track_subtype_falls_back_to_super(self):
        order = self._make_order()

        # No state change -> hook returns None -> super()'s default subtype.
        subtype = order._track_subtype({"partner_id": self.partner.id})

        self.assertNotEqual(subtype, self.env.ref("mail.mt_note"))

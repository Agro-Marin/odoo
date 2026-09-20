from odoo.addons.website_slides.tests import common


class TestCommentsCountAgreesWithChatter(common.SlidesCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.channel.sudo().write({"karma_review": 0, "karma_slide_comment": 0})
        cls.user_portal.sudo().karma = 500
        cls.channel.sudo()._action_add_members(cls.user_portal.partner_id)

    def _post_review(self, body):
        return self.slide.with_user(self.user_portal).message_post(
            body=body,
            message_type="comment",
            subtype_xmlid="mail.mt_comment",
            rating_value=5,
        )

    def _chatter_visible_messages(self):
        return (
            self.env["mail.message"]
            .sudo()
            .search(self.slide._get_domain_portal_message_fetch())
        )

    def test_bodyless_rating_is_both_shown_and_counted(self):
        message = self._post_review(body="")

        self.slide.invalidate_recordset(["comments_count"])
        visible = self._chatter_visible_messages()

        self.assertIn(
            message,
            visible,
            "a body-less rating is content; the chatter is meant to show it",
        )
        self.assertEqual(
            self.slide.comments_count,
            len(visible),
            "the badge must count exactly the messages the list displays",
        )

    def test_rating_with_a_body_is_unaffected(self):
        message = self._post_review(body="<p>Great course</p>")

        self.slide.invalidate_recordset(["comments_count"])
        visible = self._chatter_visible_messages()

        self.assertIn(message, visible)
        self.assertEqual(self.slide.comments_count, len(visible))

    def test_empty_non_rating_message_is_neither_shown_nor_counted(self):
        self.slide.with_user(self.user_portal).message_post(
            body="", message_type="comment", subtype_xmlid="mail.mt_comment"
        )

        self.slide.invalidate_recordset(["comments_count"])
        visible = self._chatter_visible_messages()

        self.assertEqual(self.slide.comments_count, len(visible))

"""The comments badge must count exactly what the comment list shows.

``mail.thread._get_portal_message_fetch_domain`` is the single definition of
"which messages the portal chatter displays". ``website_slides.comments_count``
reads it, and so does the chatter fetch controller — that shared definition is
the whole reason the badge can be trusted.

``portal_rating`` widens the rule: a rating posted without a comment has no body
and no attachment, but the star value is the content, so the chatter shows it.
That widening used to live on the *controller*, which only the chatter went
through — leaving the counter on the stricter default and undercounting its own
list by exactly the body-less ratings. It now lives on the model, so both agree.
"""

from odoo.addons.website_slides.tests import common


class TestCommentsCountAgreesWithChatter(common.SlidesCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # slide.channel.message_post refuses a comment from a member without
        # enough karma to review ("Not enough karma to review"); enrol the
        # reviewer and give them the karma the channel asks for.
        cls.channel.sudo().write({"karma_review": 0, "karma_slide_comment": 0})
        cls.user_portal.sudo().karma = 500
        cls.channel.sudo()._action_add_members(cls.user_portal.partner_id)

    def _post_review(self, body):
        """Post a rating on the channel the way the portal review flow does."""
        return self.slide.with_user(self.user_portal).message_post(
            body=body,
            message_type="comment",
            subtype_xmlid="mail.mt_comment",
            rating_value=5,
        )

    def _chatter_visible_messages(self):
        """The messages the portal chatter would fetch for this channel."""
        return self.env["mail.message"].sudo().search(
            self.slide._get_portal_message_fetch_domain()
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
        """The widening is about ratings, not about empty messages generally."""
        self.slide.with_user(self.user_portal).message_post(
            body="", message_type="comment", subtype_xmlid="mail.mt_comment"
        )

        self.slide.invalidate_recordset(["comments_count"])
        visible = self._chatter_visible_messages()

        self.assertEqual(self.slide.comments_count, len(visible))

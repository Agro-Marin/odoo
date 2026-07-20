# Part of Odoo. See LICENSE file for full copyright and licensing details.

import datetime

from odoo.tests.common import users

from odoo.addons.website_slides.tests import common as slides_common


class TestSlideOrmOverrides(slides_common.SlidesCase):
    """Regressions in ``slide.slide``'s create/write overrides.

    Each test pairs the failing case with a control that was always fine, so a
    future refactor that re-breaks the batch path cannot pass by accident.
    """

    @users("user_officer")
    def test_create_uses_default_channel_id_from_context(self):
        """create() must honour ``default_channel_id``.

        Defaults are applied inside super().create(), so reading
        vals['channel_id'] up front raised KeyError on the very pattern
        slide_channel.py and the backend views use.
        """
        slide = (
            self.env["slide.slide"]
            .with_context(default_channel_id=self.channel.id)
            .create(
                {
                    "name": "From context",
                    "slide_category": "article",
                }
            )
        )
        self.assertEqual(slide.channel_id, self.channel)

        # control: the explicit form has always worked and must keep working
        explicit = self.env["slide.slide"].create(
            {
                "name": "Explicit",
                "channel_id": self.channel.id,
                "slide_category": "article",
            }
        )
        self.assertEqual(explicit.channel_id, self.channel)

    @users("user_officer")
    def test_write_url_on_multiple_slides(self):
        """A multi-record write touching a url field must not ensure_one().

        ``_fetch_external_metadata`` is singleton-only; calling it on the whole
        recordset raised "Expected singleton", which is reachable from list-view
        multi-edit.
        """
        slides = self.env["slide.slide"].create(
            [
                {
                    "name": f"Video {index}",
                    "channel_id": self.channel.id,
                    "slide_category": "video",
                }
                for index in range(2)
            ]
        )

        # must not raise
        slides.with_context(website_slides_skip_fetch_metadata=True).write(
            {
                "url": "https://youtu.be/aaaaaaaaaaa",
            }
        )
        self.assertEqual(set(slides.mapped("url")), {"https://youtu.be/aaaaaaaaaaa"})

    @users("user_officer")
    def test_republish_is_idempotent(self):
        """Re-publishing an already-published slide is a no-op.

        It used to reset ``date_published`` (scrambling the "New" badge and the
        `latest` ordering) and re-run ``_post_publication``, so a bulk Publish on
        a list view re-notified every follower about old content.
        """
        slide = self.env["slide.slide"].create(
            {
                "name": "Already live",
                "channel_id": self.channel.id,
                "slide_category": "article",
                "is_published": True,
            }
        )
        slide.flush_recordset()
        original_date = datetime.datetime(2020, 1, 1, 0, 0, 0)
        slide.date_published = original_date
        messages_before = len(self.channel.message_ids)

        slide.write({"is_published": True})

        self.assertEqual(
            slide.date_published,
            original_date,
            "re-publishing must not reset date_published",
        )
        self.assertEqual(
            len(self.channel.message_ids),
            messages_before,
            "re-publishing must not post a duplicate publication message",
        )

    @users("user_officer")
    def test_publishing_an_unpublished_slide_still_notifies(self):
        """Control for the test above: a real state change must still fire."""
        slide = self.env["slide.slide"].create(
            {
                "name": "Draft",
                "channel_id": self.channel.id,
                "slide_category": "article",
                "is_published": False,
            }
        )
        slide.flush_recordset()

        slide.write({"is_published": True})

        self.assertTrue(slide.date_published, "publishing must stamp date_published")


class TestSlideUserFieldsIsolation(slides_common.SlidesCase):
    """``user_*`` fields must be keyed per user, not shared across a transaction."""

    def test_user_fields_are_not_shared_between_users(self):
        """The per-user computes need depends_context('uid'), not depends('uid').

        Stacking two @api.depends silently dropped the inner one (the decorator
        is an attrsetter, so the outer call overwrites it), leaving the fields
        with no context dependency and therefore a single cache entry shared by
        every user in the transaction. Whoever read first won.
        """
        member, other = self.user_emp, self.user_portal
        self.channel._action_add_members(member.partner_id | other.partner_id)
        self.env["slide.slide.partner"].create(
            {
                "slide_id": self.slide_2.id,
                "partner_id": member.partner_id.id,
                "completed": True,
                "vote": 1,
            }
        )
        self.env.flush_all()

        # read as the member FIRST: that is what used to poison the shared cache
        as_member = self.slide_2.with_user(member)
        self.assertTrue(as_member.user_has_completed)
        self.assertEqual(as_member.user_vote, 1)

        as_other = self.slide_2.with_user(other)
        self.assertFalse(
            as_other.user_has_completed,
            "a second user in the same transaction must not inherit the first user's completion",
        )
        self.assertEqual(
            as_other.user_vote,
            0,
            "a second user in the same transaction must not inherit the first user's vote",
        )

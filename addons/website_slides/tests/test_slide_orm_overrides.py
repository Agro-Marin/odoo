import datetime

from odoo.tests.common import users

from odoo.addons.website_slides.tests import common as slides_common


class TestSlideOrmOverrides(slides_common.SlidesCase):
    @users("user_officer")
    def test_create_uses_default_channel_id_from_context(self):
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

        slides.with_context(website_slides_skip_fetch_metadata=True).write(
            {
                "url": "https://youtu.be/aaaaaaaaaaa",
            }
        )
        self.assertEqual(set(slides.mapped("url")), {"https://youtu.be/aaaaaaaaaaa"})

    @users("user_officer")
    def test_republish_is_idempotent(self):
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
    def test_user_fields_are_not_shared_between_users(self):
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

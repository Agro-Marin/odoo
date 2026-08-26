from odoo.tests import tagged

from odoo.addons.mail.tests.common import mail_new_test_user
from odoo.addons.website_slides.tests import common


@tagged("post_install", "-at_install")
class TestCompletionThreshold(common.SlidesCase):
    """ "Finished" must be decided once, by counting contents.

    It used to be decided twice from the same data: the karma / completion-mail
    hook asked `completed_slides_count >= total_slides`, member_status asked
    `round(completion) == 100`. `round(100 * (n-1) / n)` reaches 100 at n >= 200,
    so on any course of 200 contents or more an attendee was flipped to
    'completed' one content early -- and since `_recompute_completion` skips a
    record that is already 'completed', finishing the last content could not
    repair it. The karma and the mail were lost permanently.
    """

    KARMA_FINISH = 50

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.learner = mail_new_test_user(
            cls.env,
            email="learner@example.com",
            groups="base.group_portal",
            login="user_learner",
            name="Lena Learner",
        )

    def _build_course(self, slide_count):
        channel = self.env["slide.channel"].create(
            {
                "name": f"Course of {slide_count}",
                "enroll": "public",
                "visibility": "public",
                "is_published": True,
                "karma_gen_channel_finish": self.KARMA_FINISH,
            }
        )
        slides = self.env["slide.slide"].create(
            [
                {
                    "name": f"Content {index}",
                    "channel_id": channel.id,
                    "slide_category": "article",
                    "html_content": "<p>x</p>",
                    "is_published": True,
                }
                for index in range(slide_count)
            ]
        )
        channel._action_add_members(self.learner.partner_id)
        channel.invalidate_recordset()
        return channel, slides

    def _membership(self, channel):
        return self.env["slide.channel.partner"].search(
            [
                ("channel_id", "=", channel.id),
                ("partner_id", "=", self.learner.partner_id.id),
            ]
        )

    def test_completion_never_reads_100_before_the_end(self):
        """The invariant, at the smallest size where rounding used to break it."""
        channel, slides = self._build_course(200)
        self.assertEqual(channel.total_slides, 200)
        slides[:199].with_user(self.learner)._action_mark_completed()

        membership = self._membership(channel)
        self.assertEqual(membership.completed_slides_count, 199)
        self.assertLess(membership.completion, 100, "199 of 200 is not 100 %")
        self.assertEqual(membership.member_status, "ongoing")
        self.assertEqual(self.learner.karma, 0)
        self.assertFalse(channel.with_user(self.learner).completed)

    def test_completion_awards_karma_on_the_last_content(self):
        channel, slides = self._build_course(200)
        slides[:199].with_user(self.learner)._action_mark_completed()
        slides[199:].with_user(self.learner)._action_mark_completed()

        membership = self._membership(channel)
        self.assertEqual(membership.completed_slides_count, 200)
        self.assertEqual(membership.completion, 100)
        self.assertEqual(membership.member_status, "completed")
        self.assertEqual(self.learner.karma, self.KARMA_FINISH)

    def test_small_course_is_unaffected(self):
        """Control: the size at which rounding never misbehaved."""
        channel, slides = self._build_course(100)
        slides[:99].with_user(self.learner)._action_mark_completed()
        membership = self._membership(channel)
        self.assertEqual(membership.completion, 99)
        self.assertEqual(membership.member_status, "ongoing")
        self.assertEqual(self.learner.karma, 0)

        slides[99:].with_user(self.learner)._action_mark_completed()
        self.assertEqual(membership.completion, 100)
        self.assertEqual(membership.member_status, "completed")
        self.assertEqual(self.learner.karma, self.KARMA_FINISH)

    def test_is_finished_is_the_only_definition(self):
        channel, slides = self._build_course(200)
        membership = self._membership(channel)
        self.assertFalse(membership._is_finished())
        slides.with_user(self.learner)._action_mark_completed()
        self.assertTrue(membership._is_finished())

    def test_channel_completion_matches_the_membership(self):
        """slide.channel.completion is a second display of the same number."""
        channel, slides = self._build_course(200)
        slides[:199].with_user(self.learner)._action_mark_completed()
        channel.invalidate_recordset()
        self.assertEqual(
            channel.with_user(self.learner).completion,
            self._membership(channel).completion,
        )
        self.assertLess(channel.with_user(self.learner).completion, 100)

import json

from odoo import http
from odoo.exceptions import AccessError
from odoo.tests import HttpCase, tagged

from odoo.addons.mail.tests.common import mail_new_test_user
from odoo.addons.website_slides.tests import common


@tagged("post_install", "-at_install")
class TestPublisherPermissions(HttpCase, common.SlidesCase):
    """`can_upload` / `can_publish` versus what the ACLs actually allow.

    slide.channel grants those two business rights to the course responsible
    whatever groups they hold -- `_compute_can_upload` returns True for
    `record.user_id == self.env.user` with no group check, on a `user_id` field
    that carries no domain. The ACLs grant that same person nothing: slide.slide,
    slide.slide.partner and slide.channel.tag are eLearning-Officer-only, and the
    officer rules are scoped to courses they are responsible for.

    Of seven publisher routes, two happened to call `.sudo()` and worked and five
    did not, so they raised AccessError for exactly the users their own guard
    admitted. These tests drive the routes, not the models, because the boundary
    lives in the controller.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user_plain = mail_new_test_user(
            cls.env,
            email="plain@example.com",
            groups="base.group_user",
            login="user_plain",
            name="Pierre Plain",
            password="user_plain",
        )
        cls.channel.sudo().user_id = cls.user_plain.id
        cls.channel.sudo().invalidate_recordset()

    def _rpc(self, route, params):
        response = self.url_open(
            route,
            data=json.dumps({"jsonrpc": "2.0", "method": "call", "params": params}),
            headers={"Content-Type": "application/json"},
        )
        return response.json()

    def test_the_persona_exists_and_is_not_exotic(self):
        """The premise of every test below."""
        channel = self.channel.with_user(self.user_plain)
        self.assertTrue(channel.can_upload)
        self.assertTrue(channel.can_publish)
        self.assertFalse(
            self.user_plain.has_group("website_slides.group_website_slides_officer")
        )
        self.assertFalse(
            self.env["slide.channel"]._fields["user_id"].domain,
            "user_id carries no domain, so any internal user can be made responsible",
        )

    def test_toggle_is_preview_as_responsible(self):
        """Was AccessError: the guard asked can_publish, the write did not sudo."""
        self.authenticate("user_plain", "user_plain")
        result = self._rpc(
            "/slides/slide/toggle_is_preview", {"slide_id": self.slide.id}
        )
        self.assertNotIn("error", result, result.get("error"))
        self.assertTrue(result["result"])
        self.assertTrue(self.slide.sudo().is_preview)

    def test_toggle_is_preview_refuses_a_non_publisher(self):
        self.authenticate("user_portal", "user_portal")
        result = self._rpc(
            "/slides/slide/toggle_is_preview", {"slide_id": self.slide.id}
        )
        self.assertIn("error", result)
        self.assertFalse(self.slide.sudo().is_preview)

    def test_category_add_as_responsible(self):
        """Was AccessError: slide.slide create is officer-only."""
        self.authenticate("user_plain", "user_plain")
        before = self.channel.sudo().slide_category_ids
        self.url_open(
            "/slides/category/add",
            data={
                "channel_id": self.channel.id,
                "name": "A new section",
                "csrf_token": http.Request.csrf_token(self),
            },
        )
        added = self.channel.sudo().slide_category_ids - before
        self.assertEqual(added.name, "A new section")

    def test_quiz_reset_as_responsible(self):
        """Was AccessError: the route searched slide.slide.partner unsudoed."""
        self.channel.sudo()._action_add_members(self.user_plain.partner_id)
        self.slide_3.with_user(self.user_plain)._action_set_viewed(
            self.user_plain.partner_id, quiz_attempts_inc=True
        )
        self.slide_3.with_user(self.user_plain)._action_mark_completed()
        self.assertTrue(self.slide_3.with_user(self.user_plain).user_has_completed)

        self.authenticate("user_plain", "user_plain")
        result = self._rpc("/slides/slide/quiz/reset", {"slide_id": self.slide_3.id})
        self.assertNotIn("error", result, result.get("error"))
        self.assertFalse(self.slide_3.with_user(self.user_plain).user_has_completed)

    def test_channel_tag_add_without_a_group_does_not_crash(self):
        """`_create_or_get_channel_tag` may return an error dict, not a recordset.

        The caller used to `.write()` on whatever came back, which is an
        AttributeError -- a 500 -- when the tag group is missing.
        """
        # user_manager: publisher rights on every course, plus the officer ACL
        # that minting a site-wide tag needs. user_officer is not the
        # responsible of this fixture's course (see setUpClass).
        self.authenticate("user_manager", "user_manager")
        result = self._rpc(
            "/slides/channel/tag/add",
            {
                "channel_id": self.channel.id,
                "tag_id": [0, {"name": "Brand new tag"}],
                "group_id": None,
            },
        )
        self.assertNotIn("data", result, "must not be a server error")
        self.assertIn("Tag Group", result["result"]["error"])

    def test_prepare_preview_requires_upload_rights(self):
        """The route drives outbound HTTP and had no authorization check at all."""
        self.authenticate("user_portal", "user_portal")
        result = self._rpc(
            "/slides/prepare_preview",
            {
                "channel_id": self.channel.id,
                "slide_category": "video",
                "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            },
        )
        self.assertIn("error", result["result"])

    def test_prepare_preview_rejects_an_unknown_category(self):
        """`slide` was bound only inside three branches -> UnboundLocalError -> 500."""
        self.authenticate("user_manager", "user_manager")
        for category in ("article", "quiz", "certification", "not-a-category"):
            result = self._rpc(
                "/slides/prepare_preview",
                {
                    "channel_id": self.channel.id,
                    "slide_category": category,
                    "url": "https://example.com/x",
                },
            )
            self.assertNotIn(
                "data", result, f"{category} must not raise a server error"
            )
            self.assertIn("error", result["result"])

    def test_slides_zero_is_not_a_server_error(self):
        """`if channel_id and not channel` skipped id 0, which IntConverter matches."""
        response = self.url_open("/slides/0")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Internal Server Error", response.text)


@tagged("post_install", "-at_install")
class TestSurveyScoping(common.SlidesCase):
    """An eLearning officer may not rewrite another officer's quiz or certification.

    ir.model.access.csv grants officers CRUD on survey.survey, survey.question
    and survey.question.answer so the quiz editor works without handing them the
    Survey app. survey's own rules are scoped to group_survey_user /
    group_survey_manager, which an officer does not hold, and
    website_slides_survey's officer rules are perm_write=0 -- so no rule
    constrained writing and the grant was model-wide.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.other_officer = mail_new_test_user(
            cls.env,
            email="other.officer@example.com",
            groups="base.group_user,website_slides.group_website_slides_officer",
            login="user_other_officer",
            name="Otto Other",
        )
        cls.other_channel = (
            cls.env["slide.channel"]
            .with_user(cls.other_officer)
            .create(
                {
                    "name": "Somebody else's course",
                    "enroll": "public",
                    "visibility": "public",
                    "is_published": True,
                }
            )
        )
        cls.other_quiz = (
            cls.env["slide.slide"]
            .with_user(cls.other_officer)
            .create(
                {
                    "name": "Somebody else's quiz",
                    "channel_id": cls.other_channel.id,
                    "slide_category": "quiz",
                    "is_published": True,
                }
            )
        )
        cls.other_quiz._check_quiz_survey()
        cls.other_question = (
            cls.env["survey.question"]
            .sudo()
            .create(
                {
                    "survey_id": cls.other_quiz.sudo().survey_id.id,
                    "title": "Whose question is this?",
                    "question_type": "simple_choice",
                    "suggested_answer_ids": [
                        (
                            0,
                            0,
                            {
                                "value": "Theirs",
                                "is_correct": True,
                                "answer_score": 1.0,
                            },
                        ),
                    ],
                }
            )
        )

    def test_officer_cannot_rewrite_another_officers_question(self):
        with self.assertRaises(AccessError):
            self.other_question.with_user(self.user_officer).write(
                {"title": "mine now"}
            )
        self.assertEqual(self.other_question.sudo().title, "Whose question is this?")

    def test_officer_cannot_rewrite_another_officers_answer(self):
        answer = self.other_question.sudo().suggested_answer_ids[0]
        with self.assertRaises(AccessError):
            answer.with_user(self.user_officer).write({"is_correct": False})
        self.assertTrue(answer.sudo().is_correct)

    def test_officer_cannot_delete_another_officers_question(self):
        with self.assertRaises(AccessError):
            self.other_question.with_user(self.user_officer).unlink()
        self.assertTrue(self.other_question.sudo().exists())

    def test_officer_keeps_their_own_quiz(self):
        """The scoping must not cost the officer their own course."""
        question = self.slide_3.sudo().survey_id.question_ids[0]
        question.with_user(self.user_officer).write({"title": "Still mine"})
        self.assertEqual(question.sudo().title, "Still mine")

    def test_the_survey_inverse_lives_beside_its_many2one(self):
        """The rules are written through it, so it cannot go back to the optional module."""
        self.assertIn("slide_ids", self.env["survey.survey"]._fields)
        self.assertEqual(self.slide_3.sudo().survey_id.slide_ids, self.slide_3.sudo())

# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import Command
from odoo.tests.common import users

from odoo.addons.website_slides.tests import common as slides_common


class TestSlideQuizSurvey(slides_common.SlidesCase):
    """Test that quiz slides correctly use survey.question for their questions."""

    @users("user_officer")
    def test_ensure_quiz_survey_creates_survey(self):
        """Calling _ensure_quiz_survey on a quiz slide without a survey creates one."""
        slide = self.env["slide.slide"].create(
            {
                "name": "Test Quiz Slide",
                "channel_id": self.channel.id,
                "slide_category": "quiz",
                "is_published": True,
            }
        )
        self.assertFalse(slide.survey_id)
        slide._ensure_quiz_survey()
        self.assertTrue(slide.survey_id)
        self.assertEqual(slide.survey_id.scoring_success_min, 100.0)
        self.assertEqual(slide.survey_id.questions_layout, "one_page")
        self.assertFalse(slide.survey_id.certification)

    @users("user_officer")
    def test_has_questions_computed(self):
        """has_questions reflects whether the linked survey has questions."""
        slide = self.env["slide.slide"].create(
            {
                "name": "Test Quiz Slide",
                "channel_id": self.channel.id,
                "slide_category": "quiz",
                "is_published": True,
            }
        )
        slide._ensure_quiz_survey()
        self.assertFalse(slide.has_questions)

        self.env["survey.question"].create(
            {
                "title": "Test Question",
                "survey_id": slide.survey_id.id,
                "question_type": "simple_choice",
                "suggested_answer_ids": [
                    Command.create(
                        {"value": "Wrong", "is_correct": False, "answer_score": 0.0}
                    ),
                    Command.create(
                        {"value": "Right", "is_correct": True, "answer_score": 1.0}
                    ),
                ],
            }
        )
        slide.invalidate_recordset(["has_questions"])
        self.assertTrue(slide.has_questions)

    @users("user_officer")
    def test_quiz_info_uses_survey_questions(self):
        """_compute_quiz_info returns correct karma info from survey-backed quiz."""
        # slide_3 has a quiz survey with questions from common.py
        quiz_info = self.slide_3._compute_quiz_info(self.user_officer.partner_id)
        self.assertEqual(quiz_info[self.slide_3.id]["quiz_karma_max"], 42)
        self.assertEqual(quiz_info[self.slide_3.id]["quiz_karma_gain"], 42)

import json

from odoo.tests import HttpCase, tagged

from odoo.addons.website_slides.tests import common


@tagged("post_install", "-at_install")
class TestQuizEditing(HttpCase, common.SlidesCase):
    """Who is allowed to see which answer is correct.

    The read half of quiz editing (`_get_slide_quiz_data`) gated `is_correct` on
    `website.group_website_designer` while the write half
    (`slide_quiz_question_add_or_update`) gates on `can_publish`. Neither
    eLearning group implies designer -- only `admin` holds it -- so a course
    publisher received `is_correct: None` for every answer, the edit form loaded
    with no radio preselected, and one click on Save stored
    `is_correct=False, answer_score=0` across the board. The quiz became
    unpassable and the course uncompletable, silently.

    The two conditions were also mutually exclusive: the edit pencil renders only
    while `not slide_completed`, and the old gate released `is_correct` only once
    completed. So it failed every single time, for everyone but admin.
    """

    def _answers_of(self, quiz_data, question):
        return next(q for q in quiz_data["slide_questions"] if q["id"] == question.id)[
            "answer_ids"
        ]

    def _rpc(self, route, params):
        response = self.url_open(
            route,
            data=json.dumps({"jsonrpc": "2.0", "method": "call", "params": params}),
            headers={"Content-Type": "application/json"},
        )
        return response.json()["result"]

    def test_the_gate_is_not_the_designer_group(self):
        """The premise: publishers are not website designers, admin is."""
        self.assertFalse(
            self.user_officer.has_group("website.group_website_designer"),
            "an eLearning officer is not a website designer",
        )
        self.assertFalse(
            self.user_manager.has_group("website.group_website_designer"),
            "an eLearning manager is not a website designer either",
        )
        self.assertTrue(
            self.env.ref("base.user_admin").has_group("website.group_website_designer"),
            "admin is -- which is why this never showed up in a demo database",
        )

    def test_publisher_receives_is_correct(self):
        self.authenticate("user_officer", "user_officer")
        data = self._rpc("/slides/slide/quiz/get", {"slide_id": self.slide_3.id})
        answers = self._answers_of(data, self.question_1)
        by_value = {answer["text_value"]: answer for answer in answers}
        self.assertTrue(
            by_value[self.answer_1.value]["is_correct"],
            "the publisher must be told which answer is correct, or editing "
            "the question silently erases it",
        )
        self.assertFalse(by_value[self.answer_2.value]["is_correct"])

    def test_learner_does_not_receive_is_correct(self):
        self.channel.sudo()._action_add_members(self.user_portal.partner_id)
        self.authenticate("user_portal", "user_portal")
        data = self._rpc("/slides/slide/quiz/get", {"slide_id": self.slide_3.id})
        answers = self._answers_of(data, self.question_1)
        self.assertTrue(
            all(answer["is_correct"] is None for answer in answers),
            "an attendee who has not passed the quiz must not be handed the key",
        )

    def test_editing_a_question_keeps_the_correct_answer(self):
        """The end-to-end defect, expressed as the payload the edit form builds.

        `_serializeForm` re-reads each radio's `.checked`; with none preselected
        it sends `is_correct: false` for every answer. Feed the route exactly
        what a correctly-populated form sends and the correct answer survives.
        """
        self.authenticate("user_officer", "user_officer")
        # The route replaces the question (delete + create), so capture what the
        # correct answer *said* before calling it.
        correct_value = self.answer_1.value
        data = self._rpc("/slides/slide/quiz/get", {"slide_id": self.slide_3.id})
        question = next(
            q for q in data["slide_questions"] if q["id"] == self.question_1.id
        )

        self._rpc(
            "/slides/slide/quiz/question_add_or_update",
            {
                "slide_id": self.slide_3.id,
                "question": question["question"],
                "sequence": 1,
                "existing_question_id": question["id"],
                "answer_ids": [
                    {
                        "sequence": index + 1,
                        "text_value": answer["text_value"],
                        "is_correct": bool(answer["is_correct"]),
                        "comment": answer["comment"] or "",
                    }
                    for index, answer in enumerate(question["answer_ids"])
                ],
            },
        )

        answers = self.slide_3.sudo().survey_id.question_ids.suggested_answer_ids
        correct = answers.filtered("is_correct")
        self.assertEqual(
            correct.value,
            correct_value,
            "editing a question must not erase which answer is correct",
        )
        self.assertEqual(correct.answer_score, 1.0)

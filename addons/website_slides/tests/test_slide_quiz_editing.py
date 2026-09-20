import json

from odoo.tests import HttpCase, tagged

from odoo.addons.website_slides.tests import common


@tagged("post_install", "-at_install")
class TestQuizEditing(HttpCase, common.SlidesCase):
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
        self.authenticate("user_officer", "user_officer")
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

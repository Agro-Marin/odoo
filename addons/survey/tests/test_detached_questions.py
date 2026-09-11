from unittest.mock import patch

from psycopg.errors import SerializationFailure

from odoo import SUPERUSER_ID, Command, api
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


class TestDetachedQuestions(TransactionCase):
    def test_detached_response_lifecycle(self):
        question = self.env["survey.question"].create(
            {
                "title": "Contact",
                "question_type": "char_box",
                "constr_mandatory": True,
            }
        )
        response = self.env["survey.user_input"].create(
            {
                "nickname": "Visitor",
                "predefined_question_ids": [Command.set(question.ids)],
            }
        )
        self.assertFalse(question.survey_id)
        self.assertFalse(question.page_id)
        self.assertEqual(response.display_name, "Visitor")
        with self.assertRaises(ValidationError):
            response._submit_answers({question.id: "   "})
        self.assertFalse(response.user_input_line_ids)
        response._submit_answers({question.id: "Hello"})
        self.assertEqual(response.state, "done")
        self.assertEqual(response.user_input_line_ids.value_char_box, "Hello")
        self.assertFalse(response.scoring_success)
        with self.assertRaises(UserError):
            response._submit_answers({question.id: "Overwrite"})
        with self.assertRaises(UserError):
            question.unlink()
        question.active = False
        self.assertEqual(response.user_input_line_ids.question_id, question)
        self.assertEqual(response.predefined_question_ids, question)
        survey = self.env["survey.survey"].create({"title": "Another survey"})
        for record, values in (
            (question, {"survey_id": survey.id}),
            (response, {"survey_id": survey.id}),
            (response, {"predefined_question_ids": [Command.clear()]}),
        ):
            with self.assertRaises(ValidationError), self.cr.savepoint():
                record.write(values)

    def test_choices_are_validated_before_saving(self):
        questions = self.env["survey.question"].create(
            [
                {
                    "title": title,
                    "question_type": "dropdown",
                    "suggested_answer_ids": [Command.create({"value": title})],
                }
                for title in ("First", "Second")
            ]
        )
        response = self.env["survey.user_input"].create(
            {
                "predefined_question_ids": [Command.set(questions[:1].ids)],
            }
        )
        for value in (questions[1].suggested_answer_ids.id, "nonsense", [True]):
            with self.assertRaises(ValidationError):
                response._submit_answers({questions[0].id: value})
        self.assertFalse(response.user_input_line_ids)
        with self.assertRaises(ValidationError):
            response._submit_answers(
                {questions[1].id: questions[1].suggested_answer_ids.id}
            )
        response._submit_answers(
            {questions[0].id: questions[0].suggested_answer_ids.id}
        )
        with self.assertRaises(ValidationError):
            questions[0].suggested_answer_ids.unlink()

    def test_detached_completion_does_not_send_survey_notifications(self):
        response = self.env["survey.user_input"].create({})
        with patch.object(
            type(self.env["mail.followers"]), "_get_recipient_data"
        ) as notify:
            response._submit_answers({})
        notify.assert_not_called()
        self.assertEqual(response.state, "done")

    def test_description_escapes_question_and_answer(self):
        question = self.env["survey.question"].create(
            {
                "title": "<script>question</script>",
                "question_type": "text_box",
            }
        )
        html = question._get_answers_description(
            {question.id: '<img src=x onerror="alert(1)">\nNext'}
        )
        self.assertNotIn("<script>", html)
        self.assertNotIn("<img", html)
        self.assertIn("<br/>", html)

    def test_choice_comment_is_extracted_before_shape_validation(self):
        from odoo.addons.survey.controllers.main import Survey

        question = self.env["survey.question"].create(
            {
                "title": "Choice with comment",
                "question_type": "multiple_choice",
                "suggested_answer_ids": [Command.create({"value": "A"})],
            }
        )
        choice = question.suggested_answer_ids.id
        controller = Survey()
        answer, comment = controller._extract_comment_from_answers(
            question, [str(choice), {"comment": " More details "}]
        )
        self.assertEqual(comment, "More details")
        self.assertFalse(question._check_answer(answer, comment))
        answer, comment = controller._extract_comment_from_answers(
            question, [str(choice), {"comment": ["invalid"]}]
        )
        self.assertTrue(question._check_answer(answer, comment))

    def test_used_choice_cannot_move_to_another_question(self):
        question, other = self.env["survey.question"].create(
            [
                {"title": title, "question_type": "dropdown"}
                for title in ("Original", "Other")
            ]
        )
        choice = self.env["survey.question.answer"].create(
            {"question_id": question.id, "value": "Recorded choice"}
        )
        response = self.env["survey.user_input"].create(
            {"predefined_question_ids": [Command.set(question.ids)]}
        )
        response._submit_answers({question.id: choice.id})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            choice.question_id = other
        self.assertEqual(response.user_input_line_ids.suggested_answer_id, choice)

    def test_used_matrix_row_cannot_be_deleted(self):
        question = self.env["survey.question"].create(
            {
                "title": "Detached matrix",
                "question_type": "matrix",
                "matrix_row_ids": [Command.create({"value": "Row"})],
                "suggested_answer_ids": [Command.create({"value": "Column"})],
            }
        )
        response = self.env["survey.user_input"].create(
            {"predefined_question_ids": [Command.set(question.ids)]}
        )
        response._submit_answers(
            {
                question.id: {
                    str(question.matrix_row_ids.id): [question.suggested_answer_ids.id]
                }
            }
        )
        with self.assertRaises(ValidationError), self.cr.savepoint():
            question.matrix_row_ids.unlink()
        self.assertTrue(response.user_input_line_ids.exists())


@tagged("post_install", "-at_install")
class TestDetachedHistoryConcurrency(TransactionCase):
    def test_stale_edits_cannot_erase_committed_answers(self):
        # Independent committed fixtures are required: the competing snapshots
        # cannot see this TransactionCase's uncommitted records.
        for operation in (
            "delete_question",
            "move_choice",
            "delete_row",
            "clear_membership",
        ):
            with self.subTest(operation=operation), self.registry.cursor() as setup_cr:
                setup = api.Environment(setup_cr, SUPERUSER_ID, {})
                question = setup["survey.question"].create(
                    {
                        "title": operation,
                        "question_type": "matrix",
                        "matrix_row_ids": [Command.create({"value": "Row"})],
                        "suggested_answer_ids": [Command.create({"value": "Column"})],
                    }
                )
                other = setup["survey.question"].create(
                    {"title": "Other", "question_type": "dropdown"}
                )
                response = setup["survey.user_input"].create(
                    {
                        "predefined_question_ids": [Command.set(question.ids)],
                    }
                )
                choice, row = question.suggested_answer_ids, question.matrix_row_ids
                setup_cr.commit()
                try:
                    with self.registry.cursor() as stale_cr:
                        stale = api.Environment(stale_cr, SUPERUSER_ID, {})
                        self.assertEqual(question.with_env(stale).title, operation)
                        with self.registry.cursor() as writer_cr:
                            writer = api.Environment(writer_cr, SUPERUSER_ID, {})
                            response.with_env(writer)._submit_answers(
                                {question.id: {str(row.id): [choice.id]}}
                            )
                            writer_cr.commit()
                        with self.assertRaises(SerializationFailure):
                            if operation == "delete_question":
                                question.with_env(stale).unlink()
                            elif operation == "move_choice":
                                choice.with_env(stale).question_id = other.id
                            elif operation == "delete_row":
                                row.with_env(stale).unlink()
                            else:
                                response.with_env(stale).predefined_question_ids = [
                                    Command.clear()
                                ]
                            stale.flush_all()
                        stale_cr.rollback()
                    setup.invalidate_all()
                    self.assertEqual(len(response.user_input_line_ids), 1)
                finally:
                    setup_cr.rollback()
                    setup.invalidate_all()
                    response.unlink()
                    (question | other).unlink()
                    setup_cr.commit()

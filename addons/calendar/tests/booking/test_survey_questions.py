from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase

from odoo.addons.mail.tests.common import mail_new_test_user


class TestAppointmentSurveyQuestions(TransactionCase):
    def test_question_is_shared_without_a_survey(self):
        question = self.env["survey.question"].create(
            {
                "title": "Diet",
                "question_type": "text_box",
            }
        )
        types = self.env["appointment.type"].create(
            [
                {
                    "name": name,
                    "question_ids": [Command.set(question.ids)],
                }
                for name in ("Lunch", "Dinner")
            ]
        )
        self.assertEqual(question.appointment_type_ids, types)
        question.title = "Dietary requirements"
        self.assertEqual(types.question_ids, question)
        self.assertFalse(question.survey_id)
        survey = self.env["survey.survey"].create({"title": "Unrelated survey"})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            question.survey_id = survey

        incomplete = self.env["survey.question"].create(
            {"title": "Unconfigured choice", "question_type": "dropdown"}
        )
        with self.assertRaises(ValidationError), self.cr.savepoint():
            incomplete.is_default = True

    def test_event_response_and_deletion(self):
        appointment = self.env["appointment.type"].create({"name": "Consultation"})
        phone = appointment._get_main_phone_question()
        self.assertEqual(phone.char_box_type, "phone")
        event = self.env["calendar.event"].create(
            {
                "name": "Consultation",
                "appointment_type_id": appointment.id,
                "start": "2026-10-01 10:00:00",
                "stop": "2026-10-01 11:00:00",
            }
        )
        response = self.env["survey.user_input"].create(
            {
                "appointment_type_id": appointment.id,
                "calendar_event_id": event.id,
                "predefined_question_ids": [Command.set(phone.ids)],
            }
        )
        response._submit_answers({phone.id: "+525555555555"})
        lines = event.appointment_answer_input_ids
        self.assertEqual(lines.value_char_box, "+525555555555")
        self.assertEqual(lines.user_input_id, response)
        event.unlink()
        self.assertFalse(response.exists())
        self.assertFalse(lines.exists())

    def test_appointment_manager_cannot_read_unrelated_survey_answers(self):
        manager = mail_new_test_user(
            self.env,
            login="appointment_survey_manager",
            groups="calendar.group_appointment_manager",
        )
        survey = self.env["survey.survey"].create({"title": "Private survey"})
        response = self.env["survey.user_input"].create({"survey_id": survey.id})
        with self.assertRaises(AccessError):
            response.with_user(manager).check_access("read")
        question = (
            self.env["survey.question"]
            .with_user(manager)
            .create(
                {
                    "title": "Reusable",
                    "question_type": "char_box",
                }
            )
        )
        self.assertFalse(question.survey_id)
        survey_manager = mail_new_test_user(
            self.env,
            login="survey_only_manager",
            groups="base.group_user,survey.group_survey_manager",
        )
        appointment = self.env["appointment.type"].create(
            {
                "name": "Private appointment",
                "is_published": False,
                "schedule_based_on": "users",
                "staff_user_ids": [Command.set(manager.ids)],
                "question_ids": [Command.set(question.ids)],
            }
        )
        event = self.env["calendar.event"].create(
            {
                "name": "Private appointment",
                "appointment_type_id": appointment.id,
                "start": "2026-10-01 10:00:00",
                "stop": "2026-10-01 11:00:00",
            }
        )
        appointment_response = self.env["survey.user_input"].create(
            {
                "appointment_type_id": appointment.id,
                "calendar_event_id": event.id,
                "predefined_question_ids": [Command.set(question.ids)],
            }
        )
        appointment_response._submit_answers({question.id: "Private answer"})
        for record in (appointment_response, appointment_response.user_input_line_ids):
            with self.assertRaises(AccessError):
                record.with_user(survey_manager).check_access("read")
            record.with_user(manager).check_access("read")

    def test_survey_officer_cannot_inject_appointment_responses(self):
        officer = mail_new_test_user(
            self.env,
            login="survey_audit_officer",
            groups="base.group_user,survey.group_survey_user",
        )
        appointment = self.env["appointment.type"].create(
            {"name": "Private appointment", "is_published": False}
        )
        event = self.env["calendar.event"].create(
            {
                "name": "Private event",
                "appointment_type_id": appointment.id,
                "start": "2026-10-01 10:00:00",
                "stop": "2026-10-01 11:00:00",
            }
        )
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.env["survey.user_input"].with_user(officer).create(
                {"appointment_type_id": appointment.id, "calendar_event_id": event.id}
            )

        generic = self.env["survey.user_input"].with_user(officer).create({})
        with self.assertRaises(AccessError), self.cr.savepoint():
            generic.write(
                {"appointment_type_id": appointment.id, "calendar_event_id": event.id}
            )

    def test_multiple_historical_respondents_keep_their_customers(self):
        appointment = self.env["appointment.type"].create({"name": "Legacy meeting"})
        question = appointment._get_main_phone_question()
        event = self.env["calendar.event"].create(
            {
                "name": "Legacy meeting",
                "appointment_type_id": appointment.id,
                "start": "2026-10-01 10:00:00",
                "stop": "2026-10-01 11:00:00",
            }
        )
        partners = self.env["res.partner"].create(
            [{"name": "First respondent"}, {"name": "Second respondent"}]
        )
        for partner in partners:
            response = self.env["survey.user_input"].create(
                {
                    "appointment_type_id": appointment.id,
                    "calendar_event_id": event.id,
                    "partner_id": partner.id,
                    "predefined_question_ids": [Command.set(question.ids)],
                }
            )
            response._submit_answers({question.id: partner.name})
        self.assertEqual(event.appointment_answer_input_ids.partner_id, partners)

    def test_survey_editor_keeps_generic_access_without_editing_appointment_data(self):
        officer = mail_new_test_user(
            self.env,
            login="survey_boundary_editor",
            groups="base.group_user,survey.group_survey_manager",
        )
        question = (
            self.env["survey.question"]
            .with_user(officer)
            .create(
                {
                    "title": "Generic question",
                    "question_type": "dropdown",
                    "suggested_answer_ids": [Command.create({"value": "A"})],
                }
            )
        )
        response = (
            self.env["survey.user_input"]
            .with_user(officer)
            .create(
                {
                    "predefined_question_ids": [Command.set(question.ids)],
                }
            )
        )
        response._submit_answers({question.id: question.suggested_answer_ids.id})
        response.check_access("read")
        response.user_input_line_ids.check_access("read")
        appointment = self.env["appointment.type"].create(
            {
                "name": "Published appointment",
                "staff_user_ids": [Command.set(self.env.user.ids)],
                "is_published": True,
                "question_ids": [Command.set(question.ids)],
            }
        )
        for record, values in (
            (question, {"title": "Unauthorized change"}),
            (question.suggested_answer_ids, {"value": "Unauthorized change"}),
        ):
            with self.assertRaises(AccessError), self.cr.savepoint():
                record.with_user(officer).write(values)
        event = self.env["calendar.event"].create(
            {
                "name": "Appointment",
                "appointment_type_id": appointment.id,
                "start": "2026-10-01 10:00:00",
                "stop": "2026-10-01 11:00:00",
            }
        )
        target = self.env["survey.user_input"].create(
            {
                "appointment_type_id": appointment.id,
                "calendar_event_id": event.id,
                "predefined_question_ids": [Command.set(question.ids)],
            }
        )
        with self.assertRaises(AccessError), self.cr.savepoint():
            response.user_input_line_ids.write({"user_input_id": target.id})
        generic_question = (
            self.env["survey.question"]
            .with_user(officer)
            .create(
                {
                    "title": "Another generic question",
                    "question_type": "dropdown",
                    "suggested_answer_ids": [Command.create({"value": "B"})],
                }
            )
        )
        with self.assertRaises(AccessError), self.cr.savepoint():
            generic_question.write(
                {"appointment_type_ids": [Command.link(appointment.id)]}
            )
        with self.assertRaises(AccessError), self.cr.savepoint():
            generic_question.suggested_answer_ids.question_id = question
        response.sudo().write(
            {"appointment_type_id": appointment.id, "calendar_event_id": event.id}
        )
        for record in (response, response.user_input_line_ids):
            record.check_access("read")
            with self.assertRaises(AccessError):
                record.check_access("write")
            with self.assertRaises(AccessError):
                record.check_access("unlink")
        records = (response, response.user_input_line_ids)
        appointment.is_published = False
        for record in records:
            with self.assertRaises(AccessError):
                record.check_access("read")

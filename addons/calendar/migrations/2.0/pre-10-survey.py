from odoo.db.schema import column_exists, create_column, table_exists
from odoo.tools import SQL


def migrate(cr, version):
    if not version or not table_exists(cr, "appointment_question"):
        return
    cr.execute(
        """
        UPDATE ir_ui_view SET arch_db = replace(replace(arch_db::text, %s, %s), %s, %s)::jsonb
         WHERE id IN (SELECT res_id FROM ir_model_data WHERE module = 'appointment_sms' AND name = 'appointment_form')
    """,
        (
            "//input[@type='phone']",
            "//t[@t-call='survey.question_form_fields']",
            "isPartnerPhoneQuestion",
            "main_phone_question",
        ),
    )
    for column in ("is_default", "is_reusable"):
        if not column_exists(cr, "survey_question", column):
            create_column(cr, "survey_question", column, "boolean")
    cr.execute("""
        CREATE TABLE appointment_survey_question_map AS
        SELECT id AS old_id, nextval('survey_question_id_seq')::integer AS new_id
          FROM appointment_question;
        INSERT INTO survey_question
            (id, title, question_type, char_box_type, active, sequence,
             question_placeholder, description, constr_mandatory,
             is_default, is_reusable, create_uid, write_uid, create_date, write_date)
        SELECT m.new_id, q.name,
               CASE q.question_type WHEN 'char' THEN 'char_box' WHEN 'phone' THEN 'char_box'
                    WHEN 'text' THEN 'text_box' WHEN 'select' THEN 'dropdown'
                    WHEN 'radio' THEN 'simple_choice' WHEN 'checkbox' THEN 'multiple_choice' END,
               CASE WHEN q.question_type = 'phone' THEN 'phone' ELSE 'text' END,
               q.active, q.sequence, q.placeholder, q.extra_comment, q.question_required,
               q.is_default, q.is_reusable, q.create_uid, q.write_uid, q.create_date, q.write_date
          FROM appointment_question q JOIN appointment_survey_question_map m ON m.old_id = q.id;
        CREATE TABLE appointment_survey_answer_map AS
        SELECT id AS old_id, nextval('survey_question_answer_id_seq')::integer AS new_id
          FROM appointment_answer;
        INSERT INTO survey_question_answer
            (id, question_id, value, sequence, create_uid, write_uid, create_date, write_date)
        SELECT a.new_id, q.new_id, old.name, old.sequence,
               old.create_uid, old.write_uid, old.create_date, old.write_date
          FROM appointment_answer old JOIN appointment_survey_answer_map a ON a.old_id = old.id
          JOIN appointment_survey_question_map q ON q.old_id = old.question_id;
        UPDATE ir_model_data d SET model = 'survey.question', res_id = m.new_id
          FROM appointment_survey_question_map m WHERE d.model = 'appointment.question' AND d.res_id = m.old_id;
        UPDATE ir_model_data d SET model = 'survey.question.answer', res_id = m.new_id
          FROM appointment_survey_answer_map m WHERE d.model = 'appointment.answer' AND d.res_id = m.old_id;
        CREATE TABLE appointment_type_survey_question_rel (
            appointment_type_id integer NOT NULL, survey_question_id integer NOT NULL,
            PRIMARY KEY (appointment_type_id, survey_question_id));
        INSERT INTO appointment_type_survey_question_rel
        SELECT r.appointment_type_id, m.new_id
          FROM appointment_type_appointment_question_rel r
          JOIN appointment_survey_question_map m ON r.appointment_question_id = m.old_id;
    """)
    # Payment's fields are initialized later in the dependency graph. Preserve
    # booking ownership before Appointment's old model metadata is removed.
    if column_exists(cr, "appointment_answer_input", "calendar_booking_id"):
        for table in ("survey_user_input", "survey_user_input_line"):
            if not column_exists(cr, table, "calendar_booking_id"):
                create_column(cr, table, "calendar_booking_id", "integer")

    for old_model, new_model, mapping in (
        ("appointment.question", "survey.question", "appointment_survey_question_map"),
        (
            "appointment.answer",
            "survey.question.answer",
            "appointment_survey_answer_map",
        ),
    ):
        cr.execute(
            SQL(
                "UPDATE ir_attachment a SET res_model=%s, res_id=m.new_id FROM %s m WHERE a.res_model=%s AND a.res_id=m.old_id",
                new_model,
                SQL.identifier(mapping),
                old_model,
            )
        )

from odoo.db.schema import column_exists, table_exists
from odoo.tools import SQL


def migrate(cr, version):
    if not version or not table_exists(cr, "appointment_survey_question_map"):
        return
    has_booking = column_exists(cr, "appointment_answer_input", "calendar_booking_id")
    booking = SQL("calendar_booking_id") if has_booking else SQL("NULL::integer")
    cr.execute(
        SQL(
            """
        CREATE TABLE appointment_survey_response_map AS
        SELECT nextval('survey_user_input_id_seq')::integer AS new_id,
               calendar_event_id, %s AS calendar_booking_id, appointment_type_id, partner_id,
               min(create_uid) AS create_uid, min(create_date) AS create_date
          FROM appointment_answer_input
         GROUP BY calendar_event_id, %s, appointment_type_id, partner_id
    """,
            booking,
            booking,
        )
    )
    cr.execute("""
        INSERT INTO survey_user_input
            (id, appointment_type_id, calendar_event_id, partner_id, state,
             access_token, create_uid, write_uid, create_date, write_date, end_datetime)
        SELECT new_id, appointment_type_id, calendar_event_id, partner_id, 'done',
               gen_random_uuid()::text, create_uid, create_uid, create_date, create_date, create_date
          FROM appointment_survey_response_map;
    """)
    if has_booking:
        cr.execute("""
            UPDATE survey_user_input s SET calendar_booking_id = m.calendar_booking_id
              FROM appointment_survey_response_map m WHERE s.id = m.new_id
        """)
    cr.execute(
        SQL(
            """
        CREATE TABLE appointment_survey_line_map AS
        SELECT a.id AS old_id, nextval('survey_user_input_line_id_seq')::integer AS new_id,
               r.new_id AS response_id
          FROM appointment_answer_input a
          JOIN appointment_survey_response_map r
            ON a.calendar_event_id IS NOT DISTINCT FROM r.calendar_event_id
           AND %s IS NOT DISTINCT FROM r.calendar_booking_id
           AND a.appointment_type_id = r.appointment_type_id
           AND a.partner_id IS NOT DISTINCT FROM r.partner_id
    """,
            SQL("a.calendar_booking_id") if has_booking else SQL("NULL::integer"),
        )
    )
    cr.execute("""
        INSERT INTO survey_question_survey_user_input_rel (survey_user_input_id, survey_question_id)
        SELECT DISTINCT m.response_id, q.new_id
          FROM appointment_answer_input a
          JOIN appointment_survey_line_map m ON a.id = m.old_id
          JOIN appointment_survey_question_map q ON a.question_id = q.old_id;
        INSERT INTO survey_user_input_line
            (id, user_input_id, question_id, question_sequence, appointment_type_id,
             calendar_event_id, partner_id, skipped, answer_type, suggested_answer_id,
             value_char_box, value_text_box, create_uid, write_uid, create_date, write_date)
        SELECT m.new_id, m.response_id, q.new_id, sq.sequence, a.appointment_type_id,
               a.calendar_event_id, a.partner_id, false,
               CASE WHEN a.value_answer_id IS NOT NULL THEN 'suggestion'
                    WHEN sq.question_type = 'text_box' THEN 'text_box' ELSE 'char_box' END,
               choice.new_id,
               CASE WHEN sq.question_type != 'text_box' THEN a.value_text_box END,
               CASE WHEN sq.question_type = 'text_box' THEN a.value_text_box END,
               a.create_uid, a.write_uid, a.create_date, a.write_date
          FROM appointment_answer_input a
          JOIN appointment_survey_line_map m ON m.old_id = a.id
          JOIN appointment_survey_question_map q ON q.old_id = a.question_id
          JOIN survey_question sq ON sq.id = q.new_id
          LEFT JOIN appointment_survey_answer_map choice ON choice.old_id = a.value_answer_id;
        UPDATE ir_attachment a SET res_model='survey.user_input.line', res_id=m.new_id
          FROM appointment_survey_line_map m WHERE a.res_model='appointment.answer.input' AND a.res_id=m.old_id;
        UPDATE ir_model_data d SET model = 'survey.user_input.line', res_id = m.new_id
          FROM appointment_survey_line_map m WHERE d.model = 'appointment.answer.input' AND d.res_id = m.old_id;
    """)
    if has_booking:
        cr.execute("""
            UPDATE survey_user_input_line l SET calendar_booking_id = s.calendar_booking_id
              FROM survey_user_input s WHERE l.user_input_id = s.id AND s.appointment_type_id IS NOT NULL
        """)
    cr.execute("SELECT count(*) FROM appointment_answer_input")
    old_count = cr.fetchone()[0]
    cr.execute(
        "SELECT count(*) FROM survey_user_input_line l JOIN appointment_survey_line_map m ON l.id=m.new_id"
    )
    if cr.fetchone()[0] != old_count:
        raise ValueError("Appointment answer migration lost rows")
    cr.execute("""
        SELECT l.id FROM survey_user_input_line l
        JOIN appointment_survey_line_map m ON m.new_id = l.id
        JOIN survey_question_answer a ON a.id = l.suggested_answer_id
        WHERE a.question_id != l.question_id LIMIT 1
    """)
    if cr.fetchone():
        raise ValueError(
            "An appointment answer references a choice from another question"
        )

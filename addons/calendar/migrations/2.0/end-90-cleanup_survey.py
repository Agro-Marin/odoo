from odoo.db.schema import table_exists
from odoo.tools import SQL


def migrate(cr, version):
    if not version or not table_exists(cr, "appointment_survey_line_map"):
        return
    for table in (
        "appointment_type_appointment_question_rel",
        "appointment_answer_input",
        "appointment_answer",
        "appointment_question",
        "appointment_survey_line_map",
        "appointment_survey_response_map",
        "appointment_survey_answer_map",
        "appointment_survey_question_map",
    ):
        if table_exists(cr, table):
            cr.execute(SQL("DROP TABLE %s CASCADE", SQL.identifier(table)))

from odoo.db.schema import table_exists


def migrate(cr, version):
    if not version or not table_exists(cr, "appointment_question"):
        return
    # Calendar's parent forms load before their former Appointment extensions.
    # Keep old question widgets out of validation until all replacement views load.
    cr.execute("""
        CREATE TABLE calendar_booking_upgrade_survey_views AS
        SELECT DISTINCT view.id, view.active
          FROM ir_ui_view view
          JOIN ir_model_data data ON data.model = 'ir.ui.view' AND data.res_id = view.id
         WHERE data.module IN ('appointment', 'appointment_account_payment', 'appointment_sms')
           AND view.active;
        UPDATE ir_ui_view SET active = false
         WHERE id IN (SELECT id FROM calendar_booking_upgrade_survey_views);
    """)

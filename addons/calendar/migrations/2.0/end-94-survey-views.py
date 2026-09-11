from odoo import SUPERUSER_ID, api
from odoo.db.schema import table_exists


def migrate(cr, version):
    if not version or not table_exists(cr, "calendar_booking_upgrade_survey_views"):
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    cr.execute("SELECT id FROM calendar_booking_upgrade_survey_views WHERE active")
    views = env["ir.ui.view"].browse([row[0] for row in cr.fetchall()]).exists()
    views.write({"active": True})
    cr.execute("DROP TABLE calendar_booking_upgrade_survey_views")

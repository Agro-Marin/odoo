from odoo.tools import SQL


def migrate(cr, version):
    if not version:
        return
    cr.execute(SQL("ALTER TABLE resource_calendar DROP COLUMN IF EXISTS schedule_type"))

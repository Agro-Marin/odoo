from odoo.db.schema import table_exists


def migrate(cr, version):
    if version and table_exists(cr, "survey_user_input"):
        cr.execute("ALTER TABLE survey_user_input ALTER COLUMN survey_id DROP NOT NULL")

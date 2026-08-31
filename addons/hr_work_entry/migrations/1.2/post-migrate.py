MODEL = "hr.user.work.entry.employee"
TABLE = "hr_user_work_entry_employee"


def migrate(cr, version):
    if not version:
        return

    cr.execute("DELETE FROM ir_model_fields WHERE model = %s", (MODEL,))
    cr.execute(
        "DELETE FROM ir_model_data WHERE model = 'ir.model' AND name = %s",
        ("model_" + TABLE,),
    )
    cr.execute("DELETE FROM ir_model WHERE model = %s", (MODEL,))
    cr.execute(f'DROP TABLE IF EXISTS "{TABLE}"')

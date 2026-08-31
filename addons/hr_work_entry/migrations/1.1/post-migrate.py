MODEL = "hr.work.entry"
TABLE = "hr_work_entry"
FIELD = "conflict"


def migrate(cr, version):
    if not version:
        return

    cr.execute(
        "DELETE FROM ir_model_fields WHERE model = %s AND name = %s", (MODEL, FIELD)
    )
    cr.execute(f'ALTER TABLE "{TABLE}" DROP COLUMN IF EXISTS "{FIELD}"')

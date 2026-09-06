def migrate(cr, version):
    if not version:
        return
    cr.execute(
        "ALTER TABLE hr_employee"
        " DROP COLUMN IF EXISTS work_email,"
        " DROP COLUMN IF EXISTS work_phone,"
        " DROP COLUMN IF EXISTS mobile_phone"
    )

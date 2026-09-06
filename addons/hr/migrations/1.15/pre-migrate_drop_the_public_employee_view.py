def migrate(cr, version):
    if not version:
        return
    cr.execute("DROP VIEW IF EXISTS hr_employee_public CASCADE")

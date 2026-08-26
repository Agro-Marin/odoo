def migrate(cr, version):
    if not version:
        return

    cr.execute(
        """
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'project_project' AND column_name = 'date'
        """
    )
    if not cr.fetchone():
        return

    cr.execute(
        """
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'project_project' AND column_name = 'date_end'
        """
    )
    if cr.fetchone():
        cr.execute(
            'UPDATE project_project SET "date_end" = "date" WHERE "date_end" IS NULL'
        )
        cr.execute('ALTER TABLE project_project DROP COLUMN "date"')
    else:
        cr.execute('ALTER TABLE project_project RENAME COLUMN "date" TO "date_end"')

    cr.execute(
        """
        ALTER TABLE project_project
          DROP CONSTRAINT IF EXISTS project_project_project_date_greater
        """
    )

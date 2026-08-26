def _column_exists(cr, table, column):
    cr.execute(
        """
        SELECT 1 FROM information_schema.columns
        WHERE table_name = %s AND column_name = %s
    """,
        [table, column],
    )
    return bool(cr.fetchone())


def migrate(cr, version):
    has_old_date_end = _column_exists(cr, "project_task", "date_end")
    has_date_closed = _column_exists(cr, "project_task", "date_closed")
    has_date_deadline = _column_exists(cr, "project_task", "date_deadline")

    if has_old_date_end and not has_date_closed:
        cr.execute("ALTER TABLE project_task RENAME COLUMN date_end TO date_closed")
        has_old_date_end = False

    if has_date_deadline:
        if _column_exists(cr, "project_task", "date_end"):
            cr.execute("""
                UPDATE project_task
                   SET date_end = date_deadline
                 WHERE date_deadline IS NOT NULL
            """)
            cr.execute("ALTER TABLE project_task DROP COLUMN date_deadline CASCADE")
        else:
            cr.execute(
                "ALTER TABLE project_task RENAME COLUMN date_deadline TO date_end"
            )

    cr.execute("""
        DELETE FROM ir_model_fields
         WHERE model = 'project.task'
           AND name = 'date_deadline'
    """)
    cr.execute("""
        UPDATE ir_model_fields
           SET name = 'date_closed'
         WHERE model = 'project.task' AND name = 'date_end'
           AND NOT EXISTS (
               SELECT 1 FROM ir_model_fields
               WHERE model = 'project.task' AND name = 'date_closed'
           )
    """)

    cr.execute("""
        UPDATE ir_ui_view
           SET arch_db = regexp_replace(
               arch_db::text,
               '(?<![_a-z])date_deadline(?![_a-z])',
               'date_end',
               'g'
           )::jsonb
         WHERE model = 'project.task'
           AND arch_db::text ~ '(?<![_a-z])date_deadline(?![_a-z])'
    """)

    cr.execute("""
        SELECT indexname FROM pg_indexes
        WHERE tablename = 'project_task'
          AND indexname LIKE '%%date_deadline%%'
    """)
    for (idx_name,) in cr.fetchall():
        cr.execute(f'DROP INDEX IF EXISTS "{idx_name}"')

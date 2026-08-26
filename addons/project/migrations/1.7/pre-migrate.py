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
    if not _column_exists(cr, "project_task", "allocated_hours"):
        return

    if not _column_exists(cr, "project_task", "planned_hours"):
        cr.execute("ALTER TABLE project_task ADD COLUMN planned_hours numeric")

    if not _column_exists(cr, "project_task", "scheduled_hours"):
        cr.execute("ALTER TABLE project_task ADD COLUMN scheduled_hours numeric")

    if not _column_exists(cr, "project_task", "planned_resources"):
        cr.execute(
            "ALTER TABLE project_task ADD COLUMN planned_resources integer DEFAULT 1"
        )
    cr.execute(
        "UPDATE project_task SET planned_resources = 1 "
        "WHERE planned_resources IS NULL OR planned_resources <= 0"
    )
    cr.execute("""
        SELECT 1 FROM pg_constraint
        WHERE conname = 'project_task_planned_resources_positive'
    """)
    if not cr.fetchone():
        cr.execute("""
            ALTER TABLE project_task
            ADD CONSTRAINT project_task_planned_resources_positive
            CHECK (planned_resources > 0)
        """)

    if not _column_exists(cr, "project_task", "allocation_state"):
        cr.execute("ALTER TABLE project_task ADD COLUMN allocation_state varchar")

    if _column_exists(cr, "project_task", "unallocated_hours"):
        cr.execute("ALTER TABLE project_task DROP COLUMN unallocated_hours")

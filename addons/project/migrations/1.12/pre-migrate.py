def _column_exists(cr, table, column) -> bool:
    cr.execute(
        """
        SELECT 1
          FROM information_schema.columns
         WHERE table_name = %s
           AND column_name = %s
        """,
        (table, column),
    )
    return bool(cr.fetchone())


def migrate(cr, version) -> None:
    if not version:
        return

    for old_name, new_name in (
        ("planned_date_start", "cpm_date_start"),
        ("planned_date_end", "cpm_date_end"),
    ):
        if _column_exists(cr, "project_task", old_name) and not _column_exists(
            cr, "project_task", new_name
        ):
            cr.execute(
                f'ALTER TABLE project_task RENAME COLUMN "{old_name}" TO "{new_name}"'
            )

    cr.execute(
        """
        UPDATE ir_exports_line
           SET name = regexp_replace(name, '\\mplanned_date_end\\M', 'cpm_date_end')
         WHERE name ~ '\\mplanned_date_end\\M'
           AND export_id IN (
                 SELECT id FROM ir_exports WHERE resource = 'project.task'
           )
        """
    )

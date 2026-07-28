"""Pre-migration for the CPM date field rename (1.12).

The fork added ``planned_date_start`` / ``planned_date_end`` to
``project.task`` as stored critical-path outputs. ``planned_date_start``
collides with ``project_enterprise`` (``auto_install``), which declares the
same name as a NON-stored compute whose inverse writes back to
``planned_date_begin`` — or, when that is unset, to ``date_end``. Enterprise's
definition wins the field merge, so every ``action_compute_critical_path()``
run silently overwrote the user's scheduled start or their deadline, and the
CPM start was never stored at all (the field has no column).

The fields are renamed to ``cpm_date_start`` / ``cpm_date_end``.

``planned_date_start`` never had a column on any database where
``project_enterprise`` was installed (i.e. all of them — it auto-installs), so
the rename is conditional on the column actually existing. ``planned_date_end``
was stored and does carry data worth keeping.

Deliberately renames rather than drops: ``cpm_date_end`` holds the last
computed schedule, which the Gantt/critical-path views read on load.
"""


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

    # Saved user-facing references to the old names (list/pivot configs,
    # exports, filters) would silently resolve to enterprise's unrelated
    # calendar alias, so retarget them too.
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

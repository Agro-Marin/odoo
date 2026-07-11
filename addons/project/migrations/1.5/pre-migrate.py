"""Rename elapsed time fields to correct PM terminology.

Old naming used ambiguous 'working_hours/days_open/close' which conflated
lead time (create→end) with cycle time (assign→end). This migration renames
columns to match standard PM definitions:

  working_hours_open  → queue_time_hours   (create → assign)
  working_days_open   → queue_time_days    (create → assign)
  working_hours_close → lead_time_hours    (create → end)
  working_days_close  → lead_time_days     (create → end)

New fields cycle_time_hours/cycle_time_days (assign→end) are added by the
ORM on module update — no migration needed for those.

Also renames avg_cycle_time → avg_lead_time on project_project and
project_history (the old 'avg_cycle_time' was actually computing lead time).
"""


def migrate(cr, version):
    # Rename columns on project_task
    task_renames = [
        ("working_hours_open", "queue_time_hours"),
        ("working_days_open", "queue_time_days"),
        ("working_hours_close", "lead_time_hours"),
        ("working_days_close", "lead_time_days"),
    ]
    for old, new in task_renames:
        cr.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'project_task' AND column_name = %s",
            [old],
        )
        if cr.fetchone():
            cr.execute(f'ALTER TABLE project_task RENAME COLUMN "{old}" TO "{new}"')

    # Rename avg_cycle_time → avg_lead_time on project_history
    cr.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = 'project_history' AND column_name = 'avg_cycle_time'",
    )
    if cr.fetchone():
        cr.execute(
            'ALTER TABLE project_history RENAME COLUMN "avg_cycle_time" TO "avg_lead_time"'
        )

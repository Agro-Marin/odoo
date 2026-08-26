def migrate(cr, version):
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

    cr.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = 'project_history' AND column_name = 'avg_cycle_time'",
    )
    if cr.fetchone():
        cr.execute(
            'ALTER TABLE project_history RENAME COLUMN "avg_cycle_time" TO "avg_lead_time"'
        )

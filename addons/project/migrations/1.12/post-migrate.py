CLOSED_STATES = ["done", "canceled"]


def migrate(cr, version) -> None:
    if not version:
        return

    cr.execute(
        """
        UPDATE project_task
           SET date_closed = COALESCE(date_last_status_change, write_date)
         WHERE state = ANY(%(closed_states)s)
           AND date_closed IS NULL
        """,
        {"closed_states": CLOSED_STATES},
    )

    cr.execute(
        """
        UPDATE project_task
           SET date_closed = NULL
         WHERE date_closed IS NOT NULL
           AND NOT (state = ANY(%(closed_states)s))
        """,
        {"closed_states": CLOSED_STATES},
    )

    cr.execute(
        """
        INSERT INTO project_task_dependency
                    (task_id, depends_on_id, dependency_type, lag_hours, project_id)
             SELECT rel.task_id, rel.depends_on_id, 'fs', 0.0, t.project_id
               FROM project_task_dependency_rel rel
               JOIN project_task t ON t.id = rel.task_id
          LEFT JOIN project_task_dependency dep
                 ON dep.task_id = rel.task_id
                AND dep.depends_on_id = rel.depends_on_id
              WHERE dep.id IS NULL
        """
    )

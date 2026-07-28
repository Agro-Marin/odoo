"""Post-migration: reconcile ``project.task.date_closed`` with ``state`` (1.12).

``date_closed`` used to be written by exactly one rule — "the task entered a
folded workflow step" — and by nothing else. It therefore disagreed with
``state`` in both directions on every existing database:

* a task closed from the state widget (the usual way) kept ``date_closed``
  NULL, so lead time, cycle time, ``deadline_met``, throughput,
  ``deadline_compliance_pct`` and the Monte-Carlo forecast all treated it as
  never delivered — and a met deadline was reported as *missed*;
* a still-open task dragged into a folded column got a closure timestamp.

``date_closed`` is now derived from ``state``. Reconcile the stored history so
the metrics stop lying about the past:

* closed task with no timestamp -> ``date_last_status_change`` (stamped on
  every ``state`` write, so for a closed task it is the closure moment),
  falling back to ``write_date``;
* open task carrying a timestamp -> cleared.

``date_last_status_change`` rather than the chatter: tracking stores selection
values as their *translated label*, so mining ``mail_tracking_value`` would
silently miss every non-English database.

Raw SQL rather than a recompute: ``_compute_date_closed`` is sticky (it never
overwrites an existing value) and has no view of the past, so a recompute
would stamp *today* on every historical task and destroy the delivery history
this repairs.

Idempotent: both statements are no-ops once the columns agree.
"""

CLOSED_STATES = ["done", "canceled"]


def migrate(cr, version) -> None:
    if not version:
        return

    # `= ANY(%s)` with a list, not `IN %s` with a tuple: this fork runs
    # psycopg3, which does not expand a tuple into an IN-list.
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

    # project.task.dependency synced itself into predecessor_ids but nothing
    # came back, so every edge drawn on the task form exists only in the M2M
    # relation table: untyped, lag-less, and invisible to the typed model that
    # the critical path reads. Materialise the missing rows with the fs/no-lag
    # default an untyped link means.
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

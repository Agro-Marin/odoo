"""Pre-migration for the sprint task relation remap (1.9).

``project.sprint.task_ids`` changes from a Many2many (relation table
``project_sprint_task_rel``) to a One2many that is the inverse of the existing
``project.task.sprint_id`` Many2one. The M2M was redundant with sprint_id and
was kept in sync one-way, so it could drift.

Steps:
1. Backfill ``project_task.sprint_id`` from the old relation table for any task
   that has no sprint set yet (existing sprint_id values are authoritative and
   left untouched). If a task appeared in several sprints in the M2M — which the
   single-valued sprint_id cannot represent — keep the highest sprint id
   deterministically.
2. Drop the now-orphaned relation table (Odoo does not remove it automatically
   when the field type changes).

Idempotent: guarded on table existence; a no-op once the table is gone.
"""


def _table_exists(cr, table):
    cr.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_name = %s",
        [table],
    )
    return bool(cr.fetchone())


def migrate(cr, version):
    if not _table_exists(cr, "project_sprint_task_rel"):
        return

    cr.execute(
        """
        UPDATE project_task t
           SET sprint_id = r.sprint_id
          FROM (
              SELECT DISTINCT ON (task_id) task_id, sprint_id
                FROM project_sprint_task_rel
               ORDER BY task_id, sprint_id DESC
          ) r
         WHERE r.task_id = t.id
           AND t.sprint_id IS NULL
        """
    )
    cr.execute("DROP TABLE project_sprint_task_rel")

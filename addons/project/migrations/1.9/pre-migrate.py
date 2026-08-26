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

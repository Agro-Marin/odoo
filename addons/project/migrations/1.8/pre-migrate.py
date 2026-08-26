def _table_exists(cr, table):
    cr.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_name = %s",
        [table],
    )
    return bool(cr.fetchone())


def migrate(cr, version):
    if _table_exists(cr, "project_baseline"):
        cr.execute(
            """
            UPDATE project_baseline
               SET is_current = FALSE
             WHERE is_current IS TRUE
               AND id NOT IN (
                   SELECT DISTINCT ON (project_id) id
                     FROM project_baseline
                    WHERE is_current IS TRUE
                    ORDER BY project_id, date_created DESC, id DESC
               )
            """
        )

    if _table_exists(cr, "project_sprint"):
        cr.execute(
            """
            UPDATE project_sprint
               SET state = 'review'
             WHERE state = 'active'
               AND id NOT IN (
                   SELECT DISTINCT ON (project_id) id
                     FROM project_sprint
                    WHERE state = 'active'
                    ORDER BY project_id, date_start DESC, id DESC
               )
            """
        )

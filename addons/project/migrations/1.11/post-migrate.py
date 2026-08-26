def migrate(cr, version):
    cr.execute(
        """
        UPDATE project_task
           SET deadline_met = CASE
                   WHEN date_end IS NOT NULL
                        AND state IN ('done', 'canceled') THEN
                       CASE
                           WHEN date_closed IS NOT NULL
                                AND date_closed <= date_end THEN 'met'
                           ELSE 'missed'
                       END
                   ELSE NULL
               END
         WHERE deadline_met IN ('true', 'false')
        """
    )

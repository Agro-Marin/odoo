def migrate(cr, version):
    cr.execute(
        """
        UPDATE project_benefit b
           SET review_reminder_date = b.review_date
          FROM mail_activity a
         WHERE a.res_model = 'project.benefit'
           AND a.res_id = b.id
           AND b.review_date IS NOT NULL
           AND b.review_reminder_date IS DISTINCT FROM b.review_date
        """
    )

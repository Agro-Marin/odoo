def migrate(cr, version):
    if not version:
        return

    cr.execute(
        """
        UPDATE mail_template t
           SET model = m.model
          FROM ir_model m
         WHERE m.id = t.model_id
           AND t.model IS DISTINCT FROM m.model
        """
    )

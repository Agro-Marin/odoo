def migrate(cr, version):
    cr.execute(
        """
        DELETE FROM ir_default a
              USING ir_default b
              WHERE a.field_id = b.field_id
                AND a.id > b.id
                AND COALESCE(a.user_id, 0) = COALESCE(b.user_id, 0)
                AND COALESCE(a.company_id, 0) = COALESCE(b.company_id, 0)
                AND COALESCE(a.condition, '') = COALESCE(b.condition, '')
        """
    )

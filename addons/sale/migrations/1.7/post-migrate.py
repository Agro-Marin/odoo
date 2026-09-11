def migrate(cr, version):
    if not version:
        return
    cr.execute(
        """
            DELETE FROM ir_default d
             USING ir_model_fields f
             WHERE f.id = d.field_id
               AND f.model = 'res.company'
               AND f.name = 'downpayment_account_id'
        """
    )

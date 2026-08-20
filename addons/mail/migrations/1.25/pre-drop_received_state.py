def migrate(cr, version):
    cr.execute("UPDATE mail_mail SET state = 'sent' WHERE state = 'received'")
    if cr.rowcount:
        cr.execute(
            "DELETE FROM ir_model_fields_selection s"
            " USING ir_model_fields f"
            " WHERE s.field_id = f.id AND f.model = 'mail.mail'"
            "   AND f.name = 'state' AND s.value = 'received'"
        )

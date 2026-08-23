def migrate(cr, version):
    cr.execute(
        """
        UPDATE mail_message_subtype
        SET res_model = 'approval.request'
        WHERE res_model = 'Approval.Request'
        """,
    )

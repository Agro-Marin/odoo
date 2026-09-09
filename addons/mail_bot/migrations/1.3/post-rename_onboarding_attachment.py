def migrate(cr, version):
    cr.execute(
        """
        UPDATE res_users
           SET odoobot_state = 'onboarding_attachment'
         WHERE odoobot_state = 'onboarding_attachement'
        """
    )

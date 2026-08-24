"""Fix the spelling of the ``onboarding_attachement`` OdooBot state.

The value carried the French spelling (*attachement*) since the module was
added. It is a stored selection value, so the rename is not just a change to
the field definition: every user paused on that step keeps the old string in
``res_users.odoobot_state`` and would fall out of the onboarding table
entirely -- ``_STEPS_BY_STATE`` would not match, and the tour would answer
them with the random banter meant for uninitialised users.
"""


def migrate(cr, version):
    cr.execute(
        """
        UPDATE res_users
           SET odoobot_state = 'onboarding_attachment'
         WHERE odoobot_state = 'onboarding_attachement'
        """
    )

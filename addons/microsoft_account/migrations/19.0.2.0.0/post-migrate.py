import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Move each user's Microsoft OAuth tokens into the vault.

    The columns are dropped rather than nulled: a nulled column still sits in
    every backup taken before it was nulled.
    """
    cr.execute(
        """
        SELECT column_name FROM information_schema.columns
         WHERE table_name = 'res_users'
           AND column_name IN ('microsoft_calendar_token', 'microsoft_calendar_rtoken')
        """
    )
    if not cr.fetchall():
        return

    cr.execute(
        """
        SELECT u.id, u.microsoft_calendar_token, u.microsoft_calendar_rtoken,
               u.login, u.company_id
          FROM res_users u
         WHERE u.microsoft_calendar_token IS NOT NULL
            OR u.microsoft_calendar_rtoken IS NOT NULL
        """
    )
    rows = cr.fetchall()

    if rows:
        from odoo import SUPERUSER_ID, api

        env = api.Environment(cr, SUPERUSER_ID, {})
        category = env.ref("credential.credential_category_oauth2")
        for user_id, access_token, refresh_token, login, company_id in rows:
            credential = env["credential.credential"].create({
                "name": f"Microsoft Calendar: {login}",
                "category_id": category.id,
                "company_id": company_id,
                "oauth_access_token": access_token or False,
                "oauth_refresh_token": refresh_token or False,
            })
            cr.execute(
                "UPDATE res_users SET microsoft_calendar_credential_id = %s WHERE id = %s",
                (credential.id, user_id),
            )
        _logger.info("Moved %s Microsoft OAuth token set(s) into the vault", len(rows))

    cr.execute(
        """
        ALTER TABLE res_users
            DROP COLUMN IF EXISTS microsoft_calendar_token,
            DROP COLUMN IF EXISTS microsoft_calendar_rtoken
        """
    )

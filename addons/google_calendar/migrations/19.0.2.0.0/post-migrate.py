import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Move each user's Google OAuth tokens into the vault (ADR-0081).

    The columns are dropped rather than nulled: a nulled column still sits in
    every backup taken before it was nulled. Needs ODOO_API_ENCRYPTION_KEY, and
    fails loudly without it -- an upgrade that encrypted nothing and dropped the
    columns anyway would destroy every token.
    """
    cr.execute(
        """
        SELECT column_name FROM information_schema.columns
         WHERE table_name = 'res_users_settings'
           AND column_name IN ('google_calendar_token', 'google_calendar_rtoken')
        """
    )
    if not cr.fetchall():
        return

    cr.execute(
        """
        SELECT s.id, s.google_calendar_token, s.google_calendar_rtoken,
               u.login, u.company_id
          FROM res_users_settings s
          JOIN res_users u ON u.id = s.user_id
         WHERE s.google_calendar_token IS NOT NULL
            OR s.google_calendar_rtoken IS NOT NULL
        """
    )
    rows = cr.fetchall()

    if rows:
        from odoo import SUPERUSER_ID, api

        env = api.Environment(cr, SUPERUSER_ID, {})
        category = env.ref("credential.credential_category_oauth2")
        for settings_id, access_token, refresh_token, login, company_id in rows:
            credential = env["credential.credential"].create({
                "name": f"Google Calendar: {login}",
                "category_id": category.id,
                "company_id": company_id,
                "oauth_access_token": access_token or False,
                "oauth_refresh_token": refresh_token or False,
            })
            cr.execute(
                "UPDATE res_users_settings SET google_calendar_credential_id = %s"
                " WHERE id = %s",
                (credential.id, settings_id),
            )
        _logger.info("Moved %s Google OAuth token set(s) into the vault", len(rows))

    cr.execute(
        """
        ALTER TABLE res_users_settings
            DROP COLUMN IF EXISTS google_calendar_token,
            DROP COLUMN IF EXISTS google_calendar_rtoken
        """
    )

import logging

_logger = logging.getLogger(__name__)

TABLES = ("ir_mail_server", "fetchmail_server")
ACCESS = "google_gmail_access_token"
REFRESH = "google_gmail_refresh_token"
LABEL = "Gmail"


def migrate(cr, version):
    """Move each mail server's Gmail tokens into the vault.

    Two tables, because the fields come from a mixin that `ir.mail_server` and
    `fetchmail.server` both inherit. The columns are dropped rather than nulled:
    a nulled column still sits in every backup taken before it was nulled. Needs
    ODOO_API_ENCRYPTION_KEY and fails loudly without it, which is the right way
    round -- an upgrade that encrypted nothing and dropped the columns anyway
    would destroy every token.
    """
    from odoo import SUPERUSER_ID, api

    env = api.Environment(cr, SUPERUSER_ID, {})
    category = None
    moved = 0

    for table in TABLES:
        cr.execute(
            """
            SELECT column_name FROM information_schema.columns
             WHERE table_name = %s AND column_name IN (%s, %s)
            """,
            (table, ACCESS, REFRESH),
        )
        if not cr.fetchall():
            continue

        cr.execute(
            f'SELECT id, name, "{ACCESS}", "{REFRESH}" FROM {table}'
            f' WHERE "{ACCESS}" IS NOT NULL OR "{REFRESH}" IS NOT NULL'
        )
        for record_id, name, access_token, refresh_token in cr.fetchall():
            if category is None:
                category = env.ref("credential.credential_category_oauth2")
            credential = env["credential.credential"].create({
                "name": f"{LABEL}: {name}",
                "category_id": category.id,
                "oauth_access_token": access_token or False,
                "oauth_refresh_token": refresh_token or False,
            })
            cr.execute(
                f"UPDATE {table} SET oauth2_credential_id = %s WHERE id = %s",
                (credential.id, record_id),
            )
            moved += 1

        cr.execute(
            f'ALTER TABLE {table} DROP COLUMN IF EXISTS "{ACCESS}",'
            f' DROP COLUMN IF EXISTS "{REFRESH}"'
        )

    if moved:
        _logger.info("Moved %s Gmail token set(s) into the vault", moved)

"""Move oauth_client_secret from api_endpoint_outbound into the vault.

The OAuth client secret used to live in a mixin-encrypted Binary column on
api_endpoint_outbound. It now lives in the credential.credential vault
(oauth_client_secret JSON accessor, added in core by the companion t23878
commit). This script is defensive: production and dev both hold zero
populated rows at migration time, so the data loop is normally a no-op and
only the orphaned columns get dropped.
"""

import logging

from odoo import SUPERUSER_ID
from odoo.api import Environment

_logger = logging.getLogger(__name__)


def _column_exists(cr, table: str, column: str) -> bool:
    """Return True if ``table.column`` exists in the current database."""
    cr.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = %s AND column_name = %s
        """,
        [table, column],
    )
    return cr.fetchone() is not None


def migrate(cr, version):
    if not version:
        return

    if not _column_exists(cr, "api_endpoint_outbound", "oauth_client_secret_encrypted"):
        _logger.info("No legacy oauth_client_secret_encrypted column; nothing to do.")
        return

    env = Environment(cr, SUPERUSER_ID, {})
    credential_model = env["credential.credential"]
    oauth2_category = env.ref(
        "base_credential_manager.credential_category_oauth2",
        raise_if_not_found=False,
    )

    cr.execute(
        """
        SELECT id, company_id, environment, oauth_client_id,
               oauth_client_secret_encrypted
        FROM api_endpoint_outbound
        WHERE oauth_client_secret_encrypted IS NOT NULL
        """
    )
    rows = cr.fetchall()
    migrated = errors = 0
    for row_id, company_id, environment, client_id, encrypted in rows:
        endpoint = env["api.endpoint.outbound"].browse(row_id)
        # The endpoint no longer inherits the encryption mixin, so decrypt
        # through the vault model (same mixin, same key env vars). Never
        # raise: one undecryptable row (retired key) must not block the
        # whole upgrade — mirrors base_credential_manager 19.0.1.0.1.
        plaintext = credential_model._decrypt_value_safe(bytes(encrypted), default=None)
        if not plaintext:
            errors += 1
            _logger.warning(
                "Endpoint %s (%s): could not decrypt legacy OAuth client "
                "secret; skipping (configure it manually on the credential).",
                row_id,
                endpoint.code,
            )
            continue
        existing = credential_model.search(
            [("service_id", "=", row_id), ("category_id", "=", oauth2_category.id)],
            limit=1,
        )
        values = {
            "oauth_client_secret": plaintext,
            "oauth_client_id": client_id or False,
        }
        if existing:
            existing.write(values)
        else:
            credential_model.create(
                {
                    "name": f"{endpoint.display_name} OAuth Client (Migrated)",
                    "category_id": oauth2_category.id,
                    "service_id": row_id,
                    "company_id": company_id or env.company.id,
                    "environment": environment or "test",
                    **values,
                }
            )
        migrated += 1

    _logger.info(
        "OAuth client secret vault migration: %s migrated, %s skipped.",
        migrated,
        errors,
    )

    # encryption_key_version belonged to the removed encryption mixin; both
    # columns are orphans once the model stops declaring them.
    cr.execute(
        "ALTER TABLE api_endpoint_outbound "
        "DROP COLUMN IF EXISTS oauth_client_secret_encrypted, "
        "DROP COLUMN IF EXISTS encryption_key_version"
    )

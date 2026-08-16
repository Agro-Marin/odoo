import json
import logging

from odoo import SUPERUSER_ID
from odoo.api import Environment

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    cr.execute(
        """
        SELECT id, credential_value_encrypted, storage_method
        FROM credential_credential
        """,
    )
    rows = cr.fetchall()
    if not rows:
        _logger.info(
            "credential 19.0.1.0.1: no existing credentials, "
            "skipping storage_method backfill.",
        )
        return

    env = Environment(cr, SUPERUSER_ID, {})
    credential_model = env["credential.credential"]

    classified = {"none": 0, "simple": 0, "json": 0}
    failed_ids = []

    for row_id, encrypted, existing in rows:
        if existing and existing != "none":
            classified[existing] = classified.get(existing, 0) + 1
            continue

        if not encrypted:
            mode = "none"
        else:
            cred = credential_model.browse(row_id)
            plaintext = cred._decrypt_value_safe(encrypted, default=None)
            if plaintext is None:
                failed_ids.append(row_id)
                _logger.warning(
                    "storage_method backfill: could not decrypt credential "
                    "id=%s. Leaving storage_method at 'none'. Investigate "
                    "key rotation or re-create the credential.",
                    row_id,
                )
                mode = "none"
            elif not plaintext:
                mode = "none"
            else:
                try:
                    parsed = json.loads(plaintext)
                    mode = "json" if isinstance(parsed, dict) else "simple"
                except json.JSONDecodeError, ValueError:
                    mode = "simple"

        cr.execute(
            """
            UPDATE credential_credential
            SET storage_method = %s
            WHERE id = %s
            """,
            [mode, row_id],
        )
        classified[mode] = classified.get(mode, 0) + 1

    _logger.info(
        "credential 19.0.1.0.1: storage_method backfill "
        "complete. none=%d simple=%d json=%d failed=%d",
        classified.get("none", 0),
        classified.get("simple", 0),
        classified.get("json", 0),
        len(failed_ids),
    )
    if failed_ids:
        _logger.warning(
            "storage_method backfill: %d rows left at 'none' due to "
            "decryption failure: %s",
            len(failed_ids),
            failed_ids[:20],
        )

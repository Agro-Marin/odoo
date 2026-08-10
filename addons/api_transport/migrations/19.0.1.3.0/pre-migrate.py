"""19.0.1.3.0: adopt ``remote.device.token_fingerprint`` as the shared column.

``credential_fingerprint`` is new on ``api.channel.mixin``: the indexed SHA-256
of a channel's shared secret, so a presented bearer token can be verified — and
its channel found — without decrypting anything.

``remote.device`` already carried exactly this value under the name
``token_fingerprint``. Renaming the column here rather than letting the ORM
create an empty one keeps every existing device authenticating across the
upgrade; without it there would be a window in which the new column is NULL and
every device's bearer token is rejected.

Runs pre-migrate so the rename happens before the ORM reconciles the schema and
concludes it must add a fresh column.
"""

import logging

_logger = logging.getLogger(__name__)


def _column_exists(cr, table, column):
    cr.execute(
        """
        SELECT 1 FROM information_schema.columns
        WHERE table_name = %s AND column_name = %s
        """,
        (table, column),
    )
    return cr.fetchone() is not None


def migrate(cr, version):
    if not version:
        return
    if not _column_exists(cr, "remote_device", "token_fingerprint"):
        return
    if _column_exists(cr, "remote_device", "credential_fingerprint"):
        # Both present: the ORM already added the new one. Carry the values over
        # and let the old column go.
        cr.execute(
            """
            UPDATE remote_device
            SET credential_fingerprint = token_fingerprint
            WHERE credential_fingerprint IS NULL AND token_fingerprint IS NOT NULL
            """
        )
        cr.execute("ALTER TABLE remote_device DROP COLUMN token_fingerprint")
        _logger.info(
            "19.0.1.3.0: merged remote_device.token_fingerprint into "
            "credential_fingerprint (%s row(s)).",
            cr.rowcount,
        )
        return
    cr.execute(
        "ALTER TABLE remote_device RENAME COLUMN token_fingerprint "
        "TO credential_fingerprint"
    )
    # The old index is named after the old column; drop it so the ORM creates
    # the one it expects rather than leaving two indexes on the same column.
    cr.execute('DROP INDEX IF EXISTS "remote_device__token_fingerprint_index"')
    _logger.info(
        "19.0.1.3.0: renamed remote_device.token_fingerprint to "
        "credential_fingerprint; every device keeps authenticating."
    )

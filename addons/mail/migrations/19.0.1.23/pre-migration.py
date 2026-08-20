import logging
import typing

if typing.TYPE_CHECKING:
    from odoo.db.cursor import Cursor

_logger = logging.getLogger(__name__)


def migrate(cr: Cursor, version: str | None) -> None:
    cr.execute(
        """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns
             WHERE table_name = 'fetchmail_server' AND column_name = 'is_ssl'
        )
        """
    )
    if not cr.fetchone()[0]:
        _logger.info("mail 1.23: fetchmail_server.is_ssl already migrated, skipping.")
        return

    cr.execute(
        """
        ALTER TABLE fetchmail_server
          ADD COLUMN IF NOT EXISTS encryption VARCHAR
        """
    )
    cr.execute(
        """
        UPDATE fetchmail_server
           SET encryption = CASE WHEN is_ssl THEN 'ssl' ELSE 'none' END
         WHERE encryption IS NULL
        """
    )
    converted = cr.rowcount
    cr.execute("ALTER TABLE fetchmail_server DROP COLUMN is_ssl")

    cr.execute(
        """
        ALTER TABLE fetchmail_server RENAME COLUMN error_date TO error_since
        """
    )

    cr.execute(
        """
        SELECT name, encryption FROM fetchmail_server
         WHERE server_type NOT IN ('local')
         ORDER BY name
        """
    )
    rows = cr.fetchall()
    if rows:
        _logger.warning(
            "mail 1.23: converted %d incoming mail server(s) to the new `encryption` "
            "field, choosing the scheme that preserves current behaviour rather than "
            "the secure one. Review each and move it to a '..._strict' variant, which "
            "validates the server certificate: %s",
            converted,
            ", ".join(f"{name} -> {encryption}" for name, encryption in rows),
        )

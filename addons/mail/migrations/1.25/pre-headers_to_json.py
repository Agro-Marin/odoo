import ast
import json
import logging
import typing

if typing.TYPE_CHECKING:
    from odoo.db.cursor import Cursor

_logger = logging.getLogger(__name__)


def migrate(cr: Cursor, version: str | None) -> None:
    cr.execute(
        """
        SELECT data_type FROM information_schema.columns
         WHERE table_name = 'mail_mail' AND column_name = 'headers'
        """
    )
    row = cr.fetchone()
    if not row:
        _logger.info("mail 1.25: no mail_mail.headers column, nothing to migrate.")
        return
    if row[0] == "jsonb":
        _logger.info("mail 1.25: mail_mail.headers is already jsonb, skipping.")
        return

    cr.execute("ALTER TABLE mail_mail RENAME COLUMN headers TO headers_repr_legacy")
    cr.execute(
        """
        ALTER TABLE mail_mail
          ADD COLUMN IF NOT EXISTS headers jsonb
        """
    )
    cr.execute(
        """
        SELECT id, headers_repr_legacy FROM mail_mail
         WHERE headers_repr_legacy IS NOT NULL AND headers_repr_legacy != ''
        """
    )
    converted, dropped = [], 0
    for mail_id, raw in cr.fetchall():
        try:
            parsed = ast.literal_eval(raw)
        except ValueError, TypeError, SyntaxError, MemoryError, RecursionError:
            parsed = None
        if not isinstance(parsed, dict):
            dropped += 1
            continue
        converted.append((mail_id, json.dumps(parsed)))

    if converted:
        cr.executemany(
            "UPDATE mail_mail SET headers = %s::jsonb WHERE id = %s",
            [(payload, mail_id) for mail_id, payload in converted],
        )
    _logger.info(
        "mail 1.25: mail_mail.headers -> jsonb, %s row(s) converted, %s "
        "unreadable row(s) left empty.",
        len(converted),
        dropped,
    )

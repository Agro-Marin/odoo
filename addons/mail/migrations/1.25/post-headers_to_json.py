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
             WHERE table_name = 'mail_mail' AND column_name = 'headers_repr_legacy'
        )
        """
    )
    if not cr.fetchone()[0]:
        return
    cr.execute("ALTER TABLE mail_mail DROP COLUMN headers_repr_legacy")
    _logger.info("mail 1.25: dropped mail_mail.headers_repr_legacy.")

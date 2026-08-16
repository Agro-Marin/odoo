import logging
import typing

if typing.TYPE_CHECKING:
    from odoo.db.cursor import Cursor

_logger = logging.getLogger(__name__)


def migrate(cr: Cursor, version: str | None) -> None:
    cr.execute(
        """
        DELETE FROM res_users_settings_volumes v
         WHERE v.guest_id IS NOT NULL
           AND NOT EXISTS (SELECT 1 FROM mail_guest g WHERE g.id = v.guest_id)
        """
    )
    if cr.rowcount:
        _logger.info(
            "mail 1.21: removed %d volume setting(s) pointing at deleted guests.",
            cr.rowcount,
        )

import logging
import typing

if typing.TYPE_CHECKING:
    from odoo.db.cursor import Cursor

_logger = logging.getLogger(__name__)

_FA_STYLE_TOKENS = {
    "fa-solid",
    "fa-regular",
    "fa-brands",
    "fa-light",
    "fa-thin",
    "fa-duotone",
    "fas",
    "far",
    "fab",
    "fal",
    "fat",
    "fad",
}


def _to_fa7(icon: str) -> str:
    tokens = icon.split()
    tokens = [tok for tok in tokens if tok != "fa"]
    if not any(tok in _FA_STYLE_TOKENS for tok in tokens):
        tokens.insert(0, "fa-solid")
    return " ".join(tokens)


def migrate(cr: Cursor, version: str | None) -> None:
    if not version:
        return
    cr.execute(
        "SELECT id, icon FROM mail_activity_type WHERE icon IS NOT NULL AND icon != ''"
    )
    remapped = [
        (new_icon, row_id)
        for row_id, icon in cr.fetchall()
        if (new_icon := _to_fa7(icon)) != icon
    ]
    for new_icon, row_id in remapped:
        cr.execute(
            "UPDATE mail_activity_type SET icon = %s WHERE id = %s", (new_icon, row_id)
        )
    if remapped:
        _logger.info(
            "mail: normalized %s activity-type icon(s) to Font Awesome 7",
            len(remapped),
        )

import logging
import typing

from odoo import api

if typing.TYPE_CHECKING:
    from odoo.db.cursor import Cursor

_logger = logging.getLogger(__name__)


def migrate(cr: "Cursor", version: str | None) -> None:
    if not version:
        return
    env = api.Environment(cr, api.SUPERUSER_ID, {})
    configs = env["pos.config"]._fill_default_sol_product()
    if configs:
        _logger.info(
            "pos_sale 1.2: set the default product on %d register(s)", len(configs)
        )

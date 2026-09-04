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
    _fill_default_sol_product(env)


def _fill_default_sol_product(env: api.Environment) -> None:
    """Give the registers that already exist the stand-in product.

    `default_product_id` carries a default, which only covers registers
    created from here on. Without this, settling a description-only sale
    order line on an existing register would still drop the line.
    """
    product = env["pos.config"]._default_sol_product()
    if not product:
        return
    configs = (
        env["pos.config"]
        .with_context(active_test=False)
        .search([("default_product_id", "=", False)])
    )
    if not configs:
        return
    _logger.info(
        "pos_sale 1.2: setting %s as the default product on %d register(s)",
        product.display_name,
        len(configs),
    )
    configs.write({"default_product_id": product.id})

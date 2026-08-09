from odoo import api


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, api.SUPERUSER_ID, {})
    minute = env.ref("uom.product_uom_minute", raise_if_not_found=False)
    if (
        minute
        and minute.relative_factor != 1.0 / 60.0  # noqa: RUF069
        and abs(minute.relative_factor * 60.0 - 1.0) < 1e-3
    ):
        minute.relative_factor = 1.0 / 60.0

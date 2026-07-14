# Part of Odoo. See LICENSE file for full copyright and licensing details.
# Fix the Minutes → Hours conversion factor: the historical value 0.0166667
# makes 60 minutes convert to 1.01 hours (1.000002 rounded UP at 2 digits).
# 1/60 rounds back to exactly 1.0. Only touch databases still carrying the
# stock value, so a deliberate user customization is preserved.

from odoo import api


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, api.SUPERUSER_ID, {})
    minute = env.ref('uom.product_uom_minute', raise_if_not_found=False)
    if (
        minute
        and minute.relative_factor != 1.0 / 60.0
        # only values meant to be 1/60 (0.0166667 or a float8->numeric
        # truncation of it); a deliberate user customization is preserved
        and abs(minute.relative_factor * 60.0 - 1.0) < 1e-3
    ):
        minute.relative_factor = 1.0 / 60.0

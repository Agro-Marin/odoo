from typing import Any

from odoo import models


class DecimalPrecision(models.Model):
    _inherit = "decimal.precision"

    def write(self, vals: dict[str, Any]) -> bool:
        res = super().write(vals)
        if "digits" in vals or "name" in vals:
            self.env["uom.uom"].invalidate_model(["rounding"])
        return res

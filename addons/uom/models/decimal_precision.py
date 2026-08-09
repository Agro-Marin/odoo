# Part of Odoo. See LICENSE file for full copyright and licensing details.

from typing import Any

from odoo import models


class DecimalPrecision(models.Model):
    _inherit = "decimal.precision"

    def write(self, vals: dict[str, Any]) -> bool:
        res = super().write(vals)
        if "digits" in vals or "name" in vals:
            # `uom.uom.rounding` is a compute with no `@api.depends` -- it reads
            # a `decimal.precision` row, which is not a field of `uom.uom`, so
            # the ORM has nothing to invalidate it on. Without this the field
            # cache kept the pre-write step while `precision_get` (ormcached,
            # and cleared by `super()`) already returned the new one, so
            # `_compute_quantity` (reads `rounding`) and `round`/`compare`/
            # `is_zero` (read `precision_get`) answered differently for the rest
            # of the transaction -- and which one you got depended on whether
            # the unit happened to be in cache already.
            self.env["uom.uom"].invalidate_model(["rounding"])
        return res

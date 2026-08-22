from typing import Any

from odoo import models


class DecimalPrecision(models.Model):
    _inherit = "decimal.precision"

    def write(self, vals: dict[str, Any]) -> bool:
        """Drop the cached `uom.uom.rounding`, which follows `digits`.

        `rounding` is a compute with no `@api.depends` -- it reads a
        `decimal.precision` row, not a field of `uom.uom`, so nothing in the
        ORM invalidates it. Base already clears the `stable` ormcache behind
        `get_precision`; this clears the field cache in front of it, so the two
        cannot disagree for the rest of the transaction.

        `write` is the only hook needed. `unlink` calls `env.invalidate_all()`
        on its own, and a second "Product Unit" row cannot be created (the
        model has a unique index on `name`), so neither can leave a stale value
        behind. The condition this used to carry (`"digits" in vals or "name"
        in vals`) named the model's only two fields, so it was always true.
        """
        res = super().write(vals)
        self.env["uom.uom"].invalidate_model(["rounding"])
        return res

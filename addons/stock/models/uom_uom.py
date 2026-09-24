from odoo import fields, models
from odoo.exceptions import UserError
from odoo.libs.debug_log import DebugLog

_debug = DebugLog(__name__)


class UomUom(models.Model):
    _inherit = "uom.uom"

    package_type_id = fields.Many2one(comodel_name="stock.package.type")
    route_ids = fields.Many2many(
        related="package_type_id.route_ids",
        string="Routes",
        help="Routes propagated from the package type",
    )

    def write(self, vals):
        keys_to_protect = {"factor", "relative_factor", "relative_uom_id"}
        if any(key in vals for key in keys_to_protect):
            changed = self.filtered(
                lambda u: (
                    any(
                        f in vals and u[f] != vals[f]
                        for f in ("factor", "relative_factor")
                    )
                    or (
                        "relative_uom_id" in vals
                        and (u.relative_uom_id.id or 0)
                        != int(vals["relative_uom_id"] or 0)
                    )
                ),
            )
            if changed:
                rescaled = (
                    self.sudo()
                    .with_context(active_test=False)
                    .search([("id", "child_of", changed.ids)])
                )
                _debug.logic("write_ratio_change", changed=changed, rescaled=rescaled)
                if rescaled._is_used_in_stock():
                    raise UserError(
                        self.env._(
                            "You cannot change the ratio of this unit of measure"
                            " as some products with this UoM, or with a unit"
                            " defined from it, have already been moved or are"
                            " currently reserved.",
                        ),
                    )
        return super().write(vals)

    def _is_used_in_stock(self):
        open_state = ("state", "not in", ("cancel", "done"))
        return bool(
            self.env["stock.move"]
            .sudo()
            .search_count([("product_uom_id", "in", self.ids), open_state], limit=1)
            or self.env["stock.move.line"]
            .sudo()
            .search_count([("product_uom_id", "in", self.ids), open_state], limit=1)
            or self.env["stock.quant"]
            .sudo()
            .search_count(
                [
                    ("product_id.product_tmpl_id.uom_id", "in", self.ids),
                    ("quantity", "!=", 0),
                ],
                limit=1,
            )
        )

    def _get_procurement_qty_and_uom(self, qty, quant_uom):
        get_param = self.env["ir.config_parameter"].sudo().get_param
        if get_param("stock.propagate_uom") == "1":
            _debug.logic("procurement_uom_propagated", uom=self.id)
            return (qty, self)
        computed_qty = self._get_quantity_stored(qty, quant_uom)
        if qty and quant_uom.is_zero(computed_qty):
            _debug.logic(
                "procurement_qty_rounds_to_zero",
                qty=qty,
                uom=self.id,
                quant_uom=quant_uom.id,
            )
            return (qty, self)
        return (computed_qty, quant_uom)

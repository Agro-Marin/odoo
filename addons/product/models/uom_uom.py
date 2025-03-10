from odoo import api, models, fields
from odoo.tools.translate import _


class UomUom(models.Model):
    _inherit = "uom.uom"

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

    product_uom_ids = fields.One2many(
        comodel_name="product.uom",
        inverse_name="uom_id",
        string="Barcodes",
        domain=lambda self: [
            "|",
            ("product_id", "=", self.env.context.get("product_id")),
            ("product_id", "in", self.env.context.get("product_ids", [])),
        ],
    )
    count_packaging_barcodes = fields.Integer(
        string="Packaging Barcodes",
        compute="_compute_count_packaging_barcodes",
    )

    # ------------------------------------------------------------
    # COMPUTE METHODS
    # ------------------------------------------------------------

    @api.depends("product_uom_ids")
    def _compute_count_packaging_barcodes(self):
        uom_to_barcode_count = dict(
            self.env["product.uom"]._read_group(
                [("uom_id", "in", self.ids)],
                ["uom_id"],
                ["barcode:count"],
            )
        )
        for uom in self:
            # We always want to show the barcodes smart button
            uom.count_packaging_barcodes = uom_to_barcode_count.get(uom, 1)

    # ------------------------------------------------------------
    # ACTIONS
    # ------------------------------------------------------------

    def action_open_packaging_barcodes(self):
        self.ensure_one()
        return {
            "name": _("Packaging Barcodes"),
            "type": "ir.actions.act_window",
            "res_model": "product.uom",
            "view_mode": "list",
            "view_id": self.env.ref("product.product_uom_list_view").id,
            "domain": [("uom_id", "=", self.id)],
        }

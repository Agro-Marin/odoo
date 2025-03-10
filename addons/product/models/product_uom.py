from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.translate import _


class ProductUom(models.Model):
    _name = "product.uom"
    _description = "Link between products and their UoMs"
    _rec_name = "barcode"

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        default=lambda self: self.env.company,
    )
    product_id = fields.Many2one(
        comodel_name="product.product",
        string="Product",
        required=True,
        ondelete="cascade",
    )
    uom_id = fields.Many2one(
        comodel_name="uom.uom",
        string="Unit",
        required=True,
        ondelete="cascade",
    )
    barcode = fields.Char(
        required=True,
        copy=False,
        index="btree_not_null",
    )

    # ------------------------------------------------------------
    # CONSTRAINT METHODS
    # ------------------------------------------------------------

    _barcode_uniq = models.Constraint(
        "UNIQUE(barcode)", "A barcode can only be assigned to one packaging."
    )

    @api.constrains("barcode")
    def _check_barcode_uniqueness(self):
        """With GS1 nomenclature, products and packagings use the same pattern. Therefore, we need
        to ensure the uniqueness between products" barcodes and packagings" ones"""
        domain = [("barcode", "in", [b for b in self.mapped("barcode") if b])]
        if self.env["product.product"].search_count(domain, limit=1):
            raise ValidationError(_("A product already uses the barcode"))

    # ------------------------------------------------------------
    # COMPUTE METHODS
    # ------------------------------------------------------------

    def _compute_display_name(self):
        if not self.env.context.get("show_variant_name"):
            return super()._compute_display_name()

        for record in self:
            record.display_name = (
                f"{record.barcode} for: {record.product_id.display_name}"
            )

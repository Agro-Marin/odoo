from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import groupby


class ProductUom(models.Model):
    _name = "product.uom"
    _description = "Link between products and their UoMs"
    _rec_name = "barcode"

    product_id = fields.Many2one(
        comodel_name="product.product",
        string="Product",
        required=True,
        ondelete="cascade",
        index=True,
    )
    uom_id = fields.Many2one(
        comodel_name="uom.uom",
        string="Unit",
        required=True,
        ondelete="cascade",
        index=True,
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        default=lambda self: self.env.company,
    )
    barcode = fields.Char(required=True, copy=False, index="btree_not_null")

    # Uniqueness is per company, mirroring `product.product`: its barcode check
    # (`_check_duplicated_product_barcodes`) scopes to `company_id in (False,
    # company)` and `test_barcode` asserts that two companies may reuse a
    # barcode. A global `unique(barcode)` contradicted that -- company B could
    # not use a barcode company A had taken -- while still missing the
    # collisions it was meant to catch (see `_check_barcode_uniqueness`).
    _barcode_company_uniq = models.UniqueIndex(
        "(barcode, company_id) NULLS NOT DISTINCT",
        "A barcode can only be assigned to one packaging within a company.",
    )

    @api.constrains("barcode", "company_id")
    def _check_barcode_uniqueness(self):
        """With GS1 nomenclature, products and packagings use the same pattern. Therefore, we need
        to ensure the uniqueness between products' barcodes and packagings' ones.

        Scoped per company, and symmetric with the product-side check: the
        previous version searched `product.product` with no company filter,
        which both rejected legitimate cross-company reuse and -- because the
        product-side check *does* filter by company -- let a genuine collision
        through when the packaging and the product belonged to different
        companies.
        """
        for company, packagings in groupby(self, lambda p: p.company_id):
            barcodes = [p.barcode for p in packagings if p.barcode]
            if not barcodes:
                continue
            domain = [("barcode", "in", barcodes)]
            if company:
                domain.append(("company_id", "in", (False, company.id)))
            if self.env["product.product"].sudo().search_count(domain, limit=1):
                raise ValidationError(_("A product already uses the barcode"))

    def _compute_display_name(self):
        if not self.env.context.get("show_variant_name"):
            return super()._compute_display_name()
        for record in self:
            record.display_name = (
                f"{record.barcode} for: {record.product_id.display_name}"
            )
        return None

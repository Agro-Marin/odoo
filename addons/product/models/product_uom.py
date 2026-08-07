from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import groupby


class ProductUom(models.Model):
    _name = "product.uom"
    _description = "Link between products and their UoMs"
    _rec_name = "barcode"
    _check_company_auto = True

    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        default=lambda self: self.env.company,
    )
    product_id = fields.Many2one(
        comodel_name="product.product",
        string="Product",
        required=True,
        check_company=True,
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
    barcode = fields.Char(
        required=True,
        copy=False,
        index="btree_not_null",
    )

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
        barcodes_by_company = {
            company: [p.barcode for p in packagings if p.barcode]
            for company, packagings in groupby(self, lambda p: p.company_id)
        }
        all_barcodes = [
            b for barcodes in barcodes_by_company.values() for b in barcodes
        ]
        if not all_barcodes:
            return
        # One query for every company in the batch rather than one per company:
        # the company scoping is a cheap filter on the result, not a reason to
        # go back to the database. `search_fetch` so the two fields read below
        # come back with the rows.
        colliding = (
            self.env["product.product"]
            .sudo()
            .search_fetch([("barcode", "in", all_barcodes)], ["barcode", "company_id"])
        )
        if not colliding:
            return
        for company, barcodes in barcodes_by_company.items():
            if not barcodes:
                continue
            wanted = set(barcodes)
            if any(
                product.barcode in wanted
                # A packaging with no company collides with any product; one
                # owned by a company only with that company's or a shared one.
                and (
                    not company
                    or not product.company_id
                    or product.company_id == company
                )
                for product in colliding
            ):
                raise ValidationError(_("A product already uses the barcode"))

    def _compute_display_name(self):
        if not self.env.context.get("show_variant_name"):
            return super()._compute_display_name()
        for record in self:
            record.display_name = (
                f"{record.barcode} for: {record.product_id.display_name}"
            )
        return None

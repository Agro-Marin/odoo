from odoo import api, fields, models
from odoo.tools.translate import _


class ProductSupplierinfo(models.Model):
    _name = "product.supplierinfo"
    _description = "Supplier Pricelist"
    _order = "sequence, min_qty DESC, price, id"
    _rec_name = "partner_id"

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        default=lambda self: self.env.company.id,
        index=1,
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        string="Currency",
        required=True,
        default=lambda self: self.env.company.currency_id.id,
    )
    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Vendor",
        required=True,
        check_company=True,
        ondelete="cascade",
    )
    product_id = fields.Many2one(
        comodel_name="product.product",
        string="Product Variant",
        compute="_compute_product_id",
        store=True,
        readonly=False,
        check_company=True,
        domain='[("product_tmpl_id", "=", product_tmpl_id)] if product_tmpl_id else []',
        help="If not set, the vendor price will apply to all variants of this product.",
    )
    product_tmpl_id = fields.Many2one(
        comodel_name="product.template",
        string="Product Template",
        check_company=True,
        ondelete="cascade",
        index=True,
    )
    count_product_variant = fields.Integer(
        related="product_tmpl_id.count_product_variant",
        string="Variant Count",
    )
    product_uom_id = fields.Many2one(
        comodel_name="uom.uom",
        string="Unit",
        compute="_compute_product_uom_id",
        store=True,
        readonly=False,
    )
    product_name = fields.Char(
        string="Vendor Product Name",
        help="This vendor's product name will be used when printing a request for quotation. "
        "Keep empty to use the internal one.",
    )
    product_code = fields.Char(
        string="Vendor Product Code",
        help="This vendor's product code will be used when printing a request for quotation. "
        "Keep empty to use the internal one.",
    )
    min_qty = fields.Float(
        string="Quantity",
        digits="Product Unit",
        required=True,
        default=0.0,
        help="The quantity to purchase from this vendor to benefit from the unit price. "
        "If a vendor unit is set, quantity should be specified in this unit, "
        "otherwise it should be specified in the default unit of the product.",
    )
    price = fields.Float(
        string="Unit Price",
        digits="Product Price",
        default=0.0,
        help="The price to purchase a product",
    )
    discount = fields.Float(
        string="Discount (%)",
        digits="Discount",
        readonly=False,
    )
    price_discounted = fields.Float(
        string="Discounted Price",
        compute="_compute_price_discounted",
    )
    date_start = fields.Date(
        string="Start Date",
        help="Start date for this vendor price",
    )
    date_end = fields.Date(
        string="End Date",
        help="End date for this vendor price",
    )
    sequence = fields.Integer(
        string="Sequence",
        default=1,
        help="Assigns the priority to the list of product vendor.",
    )
    delay = fields.Integer(
        string="Delivery Lead Time",
        required=True,
        default=1,
        help="Lead time in days between the confirmation of the purchase order and the receipt "
        "of the products in your warehouse. Used by the scheduler for automatic computation "
        "of the purchase order planning.",
    )

    # ------------------------------------------------------------
    # CRUD METHODS
    # ------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._sanitize_vals(vals)
            if not vals.get("product_uom_id") and vals.get("product_tmpl_id"):
                vals["product_uom_id"] = (
                    self.env["product.template"]
                    .browse(vals["product_tmpl_id"])
                    .uom_id.id
                )
            return super().create(vals_list)

    def write(self, vals):
        if "product_uom_id" in vals and not vals["product_uom_id"]:
            del vals["product_uom_id"]
        self._sanitize_vals(vals)
        res = super().write(vals)
        for supplier in self:
            if supplier.product_tmpl_id and not supplier.product_uom_id:
                supplier.product_uom_id = supplier.product_tmpl_id.uom_id
        return res

    # ------------------------------------------------------------
    # COMPUTE METHODS
    # ------------------------------------------------------------

    @api.depends("product_id", "product_tmpl_id")
    def _compute_product_uom_id(self):
        for rec in self:
            if not rec.product_uom_id:
                rec.product_uom_id = (
                    rec.product_id.uom_id
                    if rec.product_id
                    else rec.product_tmpl_id.uom_id
                )

    @api.depends("product_id", "product_tmpl_id")
    def _compute_price(self):
        for rec in self:
            rec.price = (
                rec.product_id.standard_price
                if rec.product_id
                else rec.product_tmpl_id.standard_price if rec.product_tmpl_id else 0.0
            )

    @api.depends("discount", "price")
    def _compute_price_discounted(self):
        for rec in self:
            rec.price_discounted = (
                rec.product_uom_id or rec.product_tmpl_id.uom_id
            )._compute_price(rec.price, rec.product_id.uom_id) * (
                1 - rec.discount / 100
            )

    @api.depends("product_id", "product_tmpl_id", "count_product_variant")
    def _compute_product_id(self):
        for rec in self:
            if self.env.get("default_product_id"):
                rec.product_id = self.env.get("default_product_id")
            elif not rec.product_id and rec.count_product_variant == 1:
                rec.product_id = rec.product_tmpl_id.product_variant_id

    # ------------------------------------------------------------
    # ONCHANGE METHODS
    # ------------------------------------------------------------

    @api.onchange("product_tmpl_id")
    def _onchange_product_tmpl_id(self):
        """Clear product variant if it no longer matches the product template."""
        if (
            self.product_id
            and self.product_id not in self.product_tmpl_id.product_variant_ids
        ):
            self.product_id = False

    # ------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------

    def _sanitize_vals(self, vals):
        """Sanitize vals to sync product variant & template on read/write."""
        # add product's product_tmpl_id if none present in vals
        if vals.get("product_id") and not vals.get("product_tmpl_id"):
            product = self.env["product.product"].browse(vals["product_id"])
            vals["product_tmpl_id"] = product.product_tmpl_id.id

    def _get_filtered_supplier(self, company_id, product_id, params=False):
        return self.filtered(
            lambda s: (not s.company_id or s.company_id.id == company_id.id)
            and (
                s.partner_id.active and (not s.product_id or s.product_id == product_id)
            )
        )

    @api.model
    def get_import_templates(self):
        return [
            {
                "label": _("Import Template for Vendor Pricelists"),
                "template": "/product/static/xls/product_supplierinfo.xls",
            }
        ]

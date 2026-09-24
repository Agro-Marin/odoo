from odoo import api, fields, models


class ProductSupplierinfo(models.Model):
    _inherit = "product.supplierinfo"

    is_subcontractor = fields.Boolean(
        string="Subcontracted",
        compute="_compute_is_subcontractor",
        help="Choose a vendor of type subcontractor if you want to subcontract the product",
    )

    @api.depends("partner_id", "product_id", "product_tmpl_id")
    def _compute_is_subcontractor(self):
        for supplier in self:
            boms = supplier.product_id.variant_bom_ids
            variants = (
                supplier.product_id or supplier.product_tmpl_id.product_variant_ids
            )
            boms |= supplier.product_tmpl_id.bom_ids.filtered_domain(
                ["|", ("product_id", "=", False), ("product_id", "in", variants.ids)]
            )
            supplier.is_subcontractor = supplier.partner_id in boms.subcontractor_ids


class ProductProduct(models.Model):
    _inherit = "product.product"

    def _prepare_sellers(self, params=False):
        if params and params.get("subcontractor_ids"):
            return (
                super()
                ._prepare_sellers(params=params)
                .filtered(lambda s: s.partner_id in params.get("subcontractor_ids"))
            )
        return super()._prepare_sellers(params=params)

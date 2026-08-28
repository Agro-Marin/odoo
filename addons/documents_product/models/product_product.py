from odoo import api, models


class ProductProduct(models.Model):
    _name = "product.product"
    _inherit = ["product.product", "mixin.documents.product"]

    def _compute_product_document_count(self):
        counts = {}
        if self:
            data = self.env["documents.document"]._read_group(
                [("res_model", "=", "product.product"), ("res_id", "in", self.ids)],
                ["res_id"],
                ["__count"],
            )
            counts = dict(data)
        for product in self:
            product.product_document_count = counts.get(product.id, 0)

    @api.readonly
    def action_view_documents(self):
        res = self.product_tmpl_id.action_view_documents()
        res["context"].update(
            {
                "default_res_model": self._name,
                "default_res_id": self.id,
                "search_default_context_variant": True,
            },
        )
        return res

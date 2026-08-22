from odoo import api, models


class ProductCategory(models.Model):
    _name = "product.category"
    _inherit = ["product.category", "mixin.pos.load"]

    @api.model
    def _load_pos_data_fields(self, config):
        return ["id", "name", "parent_id"]

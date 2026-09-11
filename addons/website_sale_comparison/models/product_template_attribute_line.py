from collections import OrderedDict

from odoo import models


class ProductTemplateAttributeLine(models.Model):
    _inherit = "product.template.attribute.line"

    def _prepare_categories_for_display(self):
        attributes = self.attribute_id
        categories = OrderedDict(
            [
                (cat, self.env["product.template.attribute.line"])
                for cat in attributes.category_id.sorted()
            ]
        )
        if any(not pa.category_id for pa in attributes):
            categories[self.env["product.attribute.category"]] = self.env[
                "product.template.attribute.line"
            ]
        for ptal in self:
            categories[ptal.attribute_id.category_id] |= ptal
        return categories

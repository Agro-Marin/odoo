from collections import OrderedDict

from odoo import models


class ProductTemplateAttributeLine(models.Model):
    _inherit = "product.template.attribute.line"

    def _prepare_single_value_for_display(self):
        single_value_lines = self.filtered(
            lambda ptal: (
                len(ptal.value_ids) == 1 and ptal.attribute_id.display_type != "multi"
            )
        )
        single_value_attributes = OrderedDict(
            [
                (pa, self.env["product.template.attribute.line"])
                for pa in single_value_lines.attribute_id
            ]
        )
        for ptal in single_value_lines:
            single_value_attributes[ptal.attribute_id] |= ptal
        return single_value_attributes

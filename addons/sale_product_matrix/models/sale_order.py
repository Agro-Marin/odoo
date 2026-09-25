from odoo import models


class SaleOrder(models.Model):
    _inherit = ["sale.order", "mixin.order.product.matrix"]

    _matrix_display_extra_price = True

    def _get_matrix_line_conflict_message(self):
        return self.env._(
            "You cannot change the quantity of a product present in multiple sale lines."
        )

    def _is_matrix_excluded_line(self, line):
        return bool(line.combo_item_id)

    def _get_matrix_report_templates(self):
        return (
            super()
            ._get_matrix_report_templates()
            .filtered(lambda template: template.product_add_mode == "matrix")
        )

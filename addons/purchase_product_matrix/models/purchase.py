from odoo import fields, models


class PurchaseOrder(models.Model):
    _inherit = ["purchase.order", "mixin.order.product.matrix"]

    def _is_date_commitment_removed_by(self, field_name):
        return (
            super()._is_date_commitment_removed_by(field_name) or field_name == "grid"
        )

    def _get_matrix_line_conflict_message(self):
        return self.env._(
            "You cannot change the quantity of a product present in multiple purchase lines."
        )


class PurchaseOrderLine(models.Model):
    _inherit = "purchase.order.line"

    product_template_id = fields.Many2one(
        comodel_name="product.template",
        related="product_id.product_tmpl_id",
        string="Product Template",
        domain=[("purchase_ok", "=", True)],
    )
    is_configurable_product = fields.Boolean(
        related="product_template_id.has_configurable_attributes",
        string="Is the product configurable?",
    )
    product_template_attribute_value_ids = fields.Many2many(
        related="product_id.product_template_attribute_value_ids",
        readonly=True,
    )

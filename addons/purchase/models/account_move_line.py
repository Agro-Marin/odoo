# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
import logging


from odoo import fields, models


_logger = logging.getLogger(__name__)

TOLERANCE = (
    0.02  # tolerance applied to the total when searching for a matching purchase order
)

class AccountMoveLine(models.Model):
    """Override AccountInvoice_line to add the link to the purchase order line it is related to"""

    _inherit = "account.move.line"

    is_downpayment = fields.Boolean()
    purchase_line_id = fields.Many2one(
        comodel_name="purchase.order.line",
        string="Purchase Order Line",
        ondelete="set null",
        copy=False,
        index="btree_not_null",
    )
    purchase_order_id = fields.Many2one(
        related="purchase_line_id.order_id",
        comodel_name="purchase.order",
        string="Purchase Order",
        readonly=True,
    )
    purchase_line_warn_msg = fields.Text(related="product_id.purchase_line_warn_msg")

    def _copy_data_extend_business_fields(self, values):
        # OVERRIDE to copy the 'purchase_line_id' field as well.
        super(AccountMoveLine, self)._copy_data_extend_business_fields(values)
        values["purchase_line_id"] = self.purchase_line_id.id

    def _prepare_line_values_for_purchase(self):
        return [
            {
                "product_id": line.product_id.id,
                "product_qty": line.quantity,
                "product_uom_id": line.product_uom_id.id,
                "price_unit": line.price_unit,
                "discount": line.discount,
            }
            for line in self
        ]

    def _related_analytic_distribution(self):
        # EXTENDS 'account'
        vals = super()._related_analytic_distribution()
        if self.purchase_line_id and not self.analytic_distribution:
            vals |= self.purchase_line_id.analytic_distribution or {}
        return vals

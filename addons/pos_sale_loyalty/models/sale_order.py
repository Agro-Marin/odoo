# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import models


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    def _get_fields_sale_order(self):
        field_names = super()._get_fields_sale_order()
        field_names.append('reward_id')
        return field_names

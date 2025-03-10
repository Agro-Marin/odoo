# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, models, fields


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    dropship_picking_count = fields.Integer("Dropship Count", compute='_compute_count_picking_ids')

    @api.depends('picking_ids.is_dropship')
    def _compute_count_picking_ids(self):
        super()._compute_count_picking_ids()
        for order in self:
            dropship_count = len(order.picking_ids.filtered(lambda p: p.is_dropship))
            order.count_picking_ids -= dropship_count
            order.dropship_picking_count = dropship_count

    def action_view_picking(self):
        return self._get_action_view_picking(self.picking_ids.filtered(lambda p: not p.is_dropship))

    def action_view_dropship(self):
        return self._get_action_view_picking(self.picking_ids.filtered(lambda p: p.is_dropship))

    def _prepare_procurement_group_vals(self):
        res = super()._prepare_procurement_group_vals()
        sale_orders = self.line_ids.sale_order_id
        if len(sale_orders) == 1:
            res['sale_id'] = sale_orders.id
        return res

# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"


    count_sale_order = fields.Integer(
        string="Number of Source Sale",
        compute='_compute_count_sale_order',
        groups='sales_team.group_sale_salesman',
    )


    @api.depends('line_ids.sale_order_id')
    def _compute_count_sale_order(self):
        for purchase in self:
            purchase.count_sale_order = len(purchase._get_sale_orders())

    def action_view_sale_orders(self):
        self.ensure_one()
        sale_order_ids = self._get_sale_orders().ids
        action = {
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
        }
        if len(sale_order_ids) == 1:
            action.update({
                'view_mode': 'form',
                'res_id': sale_order_ids[0],
            })
        else:
            action.update({
                'name': _('Sources Sale Orders %s', self.name),
                'view_mode': 'list,form',
                'domain': [('id', 'in', sale_order_ids)],
            })
        return action

    def action_cancel(self):
        result = super().action_cancel()
        self.sudo()._activity_cancel_on_sale()
        return result

    def _get_sale_orders(self):
        return self.line_ids.sale_order_id

    def _activity_cancel_on_sale(self):
        """If some PO are cancelled, we need to put an activity on their origin SO (only the open ones). Since a PO can have
        been modified by several SO, when cancelling one PO, many next activities can be schedulded on different SO."""
        sale_to_notify_map = {}  # map SO -> recordset of PO as {sale.order: set(purchase.order.line)}
        for order in self:
            for purchase_line in order.line_ids:
                if purchase_line.sale_line_id:
                    sale_order = purchase_line.sale_line_id.order_id
                    sale_to_notify_map.setdefault(sale_order, self.env['purchase.order.line'])
                    sale_to_notify_map[sale_order] |= purchase_line

        for sale_order, purchase_order_lines in sale_to_notify_map.items():
            sale_order._activity_schedule_with_view('mail.mail_activity_data_warning',
                user_id=sale_order.user_id.id or self.env.uid,
                views_or_xmlid='sale_purchase.exception_sale_on_purchase_cancellation',
                render_context={
                    'purchase_orders': purchase_order_lines.mapped('order_id'),
                    'purchase_order_lines': purchase_order_lines,
            })


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'


    sale_order_id = fields.Many2one(
        related='sale_line_id.order_id', string="Sale Order",
    )
    sale_line_id = fields.Many2one(
        comodel_name='sale.order.line',
        string="Origin Sale Item",
        copy=False,
        index='btree_not_null',
    )

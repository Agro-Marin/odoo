# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _


class SaleOrder(models.Model):
    _name = 'sale.order'
    _inherit = ['sale.order', 'pos.load.mixin']

    pos_order_line_ids = fields.One2many('pos.order.line', 'sale_order_origin_id', string="Order lines Transfered to Point of Sale", readonly=True, groups="point_of_sale.group_pos_user")
    pos_order_count = fields.Integer(string='Pos Order Count', compute='_count_pos_order', readonly=True, groups="point_of_sale.group_pos_user")
    amount_unpaid = fields.Monetary(
        string="Amount To Pay In POS",
        help="Amount left to pay in POS to avoid double payment or double invoicing.",
        compute='_compute_amount_unpaid',
        store=True,
    )

    @api.model
    def _load_pos_data_domain(self, data):
        return [['pos_order_line_ids.order_id.state', '=', 'draft']]

    @api.model
    def _load_pos_data_fields(self, config_id):
        return ['name', 'state', 'user_id', 'line_ids', 'partner_id', 'pricelist_id', 'fiscal_position_id', 'amount_total', 'amount_untaxed', 'amount_unpaid',
            'picking_ids', 'partner_shipping_id', 'partner_invoice_id', 'date_order', 'write_date']

    def load_sale_order_from_pos(self, config_id):
        product_ids = self.order_line.product_id.ids
        product_tmpls = self.env['product.template'].load_product_from_pos(
            config_id,
            [('product_variant_ids.id', 'in', product_ids)]
        )
        sale_order_fields = self._load_pos_data_fields(config_id)
        sale_order_read = self.read(sale_order_fields, load=False)
        sale_order_line_fields = self.order_line._load_pos_data_fields(config_id)
        sale_order_line_read = self.order_line.read(sale_order_line_fields, load=False)
        partner_fields = self.env['res.partner']._load_pos_data_fields(config_id)

        return {
            'sale.order': sale_order_read,
            'sale.order.line': sale_order_line_read,
            'res.partner': self.partner_id.read(partner_fields, load=False),
            **product_tmpls,
        }

    def _count_pos_order(self):
        for order in self:
            linked_orders = order.pos_order_line_ids.mapped('order_id')
            order.pos_order_count = len(linked_orders)

    def action_view_pos_order(self):
        self.ensure_one()
        linked_orders = self.pos_order_line_ids.mapped('order_id')
        return {
            'type': 'ir.actions.act_window',
            'name': _('Linked POS Orders'),
            'res_model': 'pos.order',
            'view_mode': 'list,form',
            'domain': [('id', 'in', linked_orders.ids)],
        }

    @api.depends('line_ids', 'amount_total', 'line_ids.invoice_line_ids.parent_state', 'line_ids.invoice_line_ids.price_total', 'line_ids.pos_order_line_ids')
    def _compute_amount_unpaid(self):
        for sale_order in self:
            total_invoice_paid = sum(sale_order.line_ids.filtered(lambda l: not l.display_type).mapped('invoice_line_ids').filtered(lambda l: l.parent_state != 'cancel').mapped('price_total'))
            total_pos_paid = sum(sale_order.line_ids.filtered(lambda l: not l.display_type).mapped('pos_order_line_ids.price_subtotal_incl'))
            sale_order.amount_unpaid = sale_order.amount_total - (total_invoice_paid + total_pos_paid)

    @api.depends('line_ids.pos_order_line_ids')
    def _compute_amount_invoiced(self):
        super()._compute_amount_invoiced()
        for order in self:
            if order.invoice_state == 'done':
                continue

            # We need to account for the downpayment paid in POS with and without invoice
            amount_to_invoice_taxinc = sum(
                order.sudo().pos_order_line_ids.filtered(
                    lambda pol: pol.sale_order_line_id.is_downpayment
                ).mapped('price_subtotal_incl')
            )
            amount_invoiced_taxinc = sum(
                order.sudo().pos_order_line_ids.filtered(
                    lambda pol: pol.order_id.state in ['paid', 'done', 'invoiced']
                    and pol.sale_order_line_id.is_downpayment
                ).mapped('price_subtotal_incl')
            )
            order.amount_to_invoice_taxinc -= amount_to_invoice_taxinc
            order.amount_invoiced_taxinc += amount_invoiced_taxinc


class SaleOrderLine(models.Model):
    _name = 'sale.order.line'
    _inherit = ['sale.order.line', 'pos.load.mixin']

    pos_order_line_ids = fields.One2many('pos.order.line', 'sale_order_line_id', string="Order lines Transfered to Point of Sale", readonly=True, groups="point_of_sale.group_pos_user")

    @api.model
    def _load_pos_data_domain(self, data):
        return [('order_id', 'in', [order['id'] for order in data['sale.order']])]

    @api.model
    def _load_pos_data_fields(self, config_id):
        return ['discount', 'display_name', 'price_total', 'price_unit', 'product_id', 'product_uom_qty', 'qty_transfered',
            'qty_invoiced', 'qty_to_invoice', 'display_type', 'name', 'tax_ids', 'is_downpayment', 'write_date']

    @api.depends('pos_order_line_ids.qty', 'pos_order_line_ids.order_id.picking_ids', 'pos_order_line_ids.order_id.picking_ids.state')
    def _compute_qty_transfered(self):
        super()._compute_qty_transfered()
        for sale_line in self:
            pos_lines = sale_line.pos_order_line_ids.filtered(lambda order_line: order_line.order_id.state not in ['cancel', 'draft'])
            if all(picking.state == 'done' for picking in pos_lines.order_id.picking_ids):
                sale_line.qty_transfered += sum((self._convert_qty(sale_line, pos_line.qty, 'p2s') for pos_line in pos_lines if sale_line.product_id.type != 'service'), 0)

    @api.depends('pos_order_line_ids', 'pos_order_line_ids.qty')
    def _compute_invoice_amounts(self):
        super()._compute_invoice_amounts()
        for sale_line in self:
            pos_lines = sale_line.pos_order_line_ids.filtered(lambda order_line: order_line.order_id.state not in ['cancel', 'draft'])
            sale_line.qty_invoiced += sum([self._convert_qty(sale_line, pos_line.qty, 'p2s') for pos_line in pos_lines], 0)
            sale_line.amount_invoiced_taxexc += sum(sale_line.pos_order_line_ids.mapped('price_subtotal'))

    def _get_sale_order_fields(self):
        return ["product_id", "display_name", "price_unit", "product_uom_qty", "tax_ids", "qty_transfered", "qty_invoiced", "discount", "qty_to_invoice", "price_total", "is_downpayment"]

    @api.model
    def _convert_qty(self, sale_line, qty, direction):
        """Converts the given QTY based on the given SALE_LINE and DIR.

        if DIR='s2p': convert from sale line uom to product uom
        if DIR='p2s': convert from product uom to sale line uom
        """
        product_uom = sale_line.product_id.uom_id
        sale_line_uom = sale_line.product_uom_id
        if direction == 's2p':
            return sale_line_uom._compute_quantity(qty, product_uom, False)
        elif direction == 'p2s':
            return product_uom._compute_quantity(qty, sale_line_uom, False)

    def unlink(self):
        # do not delete downpayment lines created from pos
        pos_downpayment_lines = self.filtered(lambda line: line.is_downpayment and line.sudo().pos_order_line_ids)
        return super(SaleOrderLine, self - pos_downpayment_lines).unlink()

    def _get_downpayment_line_price_unit(self, invoices):
        return super()._get_downpayment_line_price_unit(invoices) + sum(
            pol.price_unit for pol in self.sudo().pos_order_line_ids
        )

    @api.depends('product_id', 'pos_order_line_ids')
    def _compute_name(self):
        for sol in self:
            if sol.sudo().pos_order_line_ids:
                downpayment_sols = sol.pos_order_line_ids.mapped('refunded_orderline_id.sale_order_line_id')
                for downpayment_sol in downpayment_sols:
                    downpayment_sol.name = _("%(line_description)s (Cancelled)", line_description=downpayment_sol.name)
            else:
                super()._compute_name()

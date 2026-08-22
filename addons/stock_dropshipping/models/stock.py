# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models
from odoo.fields import Domain


class StockRule(models.Model):
    _inherit = 'stock.rule'

    @api.model
    def _get_procurements_to_merge_groupby(self, procurement):
        """ Do not group purchase order line if they are linked to different
        sale order line. The purpose is to compute the delivered quantities.
        """
        return procurement.values.get('sale_line_id'), super()._get_procurements_to_merge_groupby(procurement)

    def _get_partner_id(self, values, rule):
        route_id = self.env['ir.model.data']._xmlid_to_res_id('stock_dropshipping.route_drop_shipping')
        if route_id and rule.route_id.id == route_id:
            return False
        return super()._get_partner_id(values, rule)

    def _get_picking_type_code_domain(self):
        codes = super()._get_picking_type_code_domain()
        if self.action == 'buy':
            codes = [*codes, 'dropship']
        return codes

    @api.model
    def _get_rule_scope_domain(self, values):
        # On `_get_rule_scope_domain`, not `_get_rule_domain`: this narrowing
        # reads `sale_line_id`, and `_get_rules_batch` keys its groups on the
        # scope domain. Applied one level up it was invisible to that key, so a
        # sale-line procurement batched next to one without lost the
        # restriction -- or imposed it on the other -- depending on which of the
        # two sorted first.
        domain = super()._get_rule_scope_domain(values)
        if 'sale_line_id' in values and values.get('company_id'):
            domain &= Domain('company_id', '=', values['company_id'].id)
        return domain


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    is_dropship = fields.Boolean("Is a Dropship", compute='_compute_is_dropship')

    @api.depends('location_dest_id.usage', 'location_dest_id.company_id', 'location_id.usage', 'location_id.company_id')
    def _compute_is_dropship(self):
        for picking in self:
            source, dest = picking.location_id, picking.location_dest_id
            picking.is_dropship = (source.usage == 'supplier' or (source.usage == 'transit' and not source.company_id)) \
                              and (dest.usage == 'customer' or (dest.usage == 'transit' and not dest.company_id))

    def _is_to_external_location(self):
        self.ensure_one()
        return super()._is_to_external_location() or self.is_dropship


class StockPickingType(models.Model):
    _inherit = 'stock.picking.type'

    code = fields.Selection(
        selection_add=[('dropship', 'Dropship')], ondelete={'dropship': lambda recs: recs.write({'code': 'outgoing', 'active': False})})

    def _compute_default_location_src_id(self):
        dropship_types = self.filtered(lambda pt: pt.code == 'dropship')
        dropship_types.default_location_src_id = self.env.ref('stock.stock_location_suppliers').id

        super(StockPickingType, self - dropship_types)._compute_default_location_src_id()

    def _compute_default_location_dest_id(self):
        dropship_types = self.filtered(lambda pt: pt.code == 'dropship')
        dropship_types.default_location_dest_id = self.env.ref('stock.stock_location_customers').id

        super(StockPickingType, self - dropship_types)._compute_default_location_dest_id()

    @api.depends('default_location_src_id', 'default_location_dest_id')
    def _compute_warehouse_id(self):
        super()._compute_warehouse_id()
        for picking_type in self:
            if picking_type.code == 'dropship':
                picking_type.warehouse_id = False

    @api.model
    def _transfer_codes(self):
        return super()._transfer_codes() | {'dropship'}


class StockLot(models.Model):
    _inherit = 'stock.lot'

    def _get_partners_from_deliveries(self, pickings):
        # For a dropship the goods never transit through our company, so the
        # relevant partner is the sale's shipping address, not the picking's.
        # A recordset, not a list of ids: a picking with no partner contributed a
        # False, and assigning [id, False] to a Many2many raises MissingError
        # rather than ignoring it -- which a transfer reached through
        # `produce_line_ids`, or a dropship with no sale order, produces.
        partners = self.env['res.partner']
        for picking in pickings:
            partners |= (
                picking.sale_id.partner_shipping_id
                if picking.is_dropship
                else picking.partner_id
            )
        return partners

    def _get_outgoing_domain(self):
        return super()._get_outgoing_domain() | Domain([
            ('location_dest_id.usage', '=', 'customer'),
            ('location_id.usage', '=', 'supplier'),
        ])

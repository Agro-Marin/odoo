# Part of Odoo. See LICENSE file for full copyright and licensing details.
import datetime

from odoo import api, fields, models
from odoo.fields import Domain


class ProductProduct(models.Model):
    _inherit = "product.product"

    def _prepare_quantities_vals(self, filters, location_domains=None):
        return super(
            ProductProduct,
            self.with_context(with_expiration=datetime.date.today()),
        )._prepare_quantities_vals(filters, location_domains=location_domains)

    # `get_depends` unions `@api.depends` over the whole MRO, so this adds the one
    # column stock cannot name: `removal_date` is defined here, and stock's list
    # would raise at registry load in a database without this module.
    @api.depends_context('with_expiration', 'fresh_qty_forecast')
    @api.depends('stock_quant_ids.removal_date')
    def _compute_quantities(self):
        return super()._compute_quantities()

    def _expired_quant_domain(self, domain_quant, to_date):
        if not self.env.context.get('with_expiration'):
            return None
        max_date = (
            to_date
            if to_date and self.env.context.get('fresh_qty_forecast')
            else self.env.context['with_expiration']
        )
        return domain_quant & Domain([('removal_date', '<=', max_date)])

    qty_free = fields.Float(help="Available quantity (computed as Quantity On Hand "
             "- reserved quantity - quantity to remove)\n"
             "In a context with a single Stock Location, this includes "
             "goods stored in this location, or any of its children.\n"
             "In a context with a single Warehouse, this includes "
             "goods stored in the Stock Location of this Warehouse, or any "
             "of its children.\n"
             "Otherwise, this includes goods stored in any Stock Location "
             "with 'internal' type.")

    qty_available_virtual = fields.Float(help="Forecast quantity (computed as Quantity On Hand "
             "- Outgoing + Incoming - Quantity to Remove)\n"
             "In a context with a single Stock Location, this includes "
             "goods stored in this location, or any of its children.\n"
             "In a context with a single Warehouse, this includes "
             "goods stored in the Stock Location of this Warehouse, or any "
             "of its children.\n"
             "Otherwise, this includes goods stored in any Stock Location "
             "with 'internal' type.")


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    # The template sums its variants, so it caches per the same two keys.
    @api.depends_context('with_expiration', 'fresh_qty_forecast')
    def _compute_quantities(self):
        return super()._compute_quantities()

    use_expiration_date = fields.Boolean(string='Use Expiration Date',
        help='When this box is ticked, you have the possibility to specify dates to manage'
        ' product expiration, on the product and on the corresponding lot/serial numbers')
    expiration_time = fields.Integer(string='Expiration Date',
        help='Number of days after the receipt of the products (from the vendor'
        ' or in stock after production) after which the goods may become dangerous'
        ' and must not be consumed. It will be computed on the lot/serial number.')
    use_time = fields.Integer(string='Best Before Date',
        help='Number of days before the Expiration Date after which the goods starts'
        ' deteriorating, without being dangerous yet. It will be computed on the lot/serial number.')
    removal_time = fields.Integer(string='Removal Date',
        help='Number of days before the Expiration Date after which the goods'
        ' should be removed from the stock and not be counted in the Fresh On Hand Stock anymore.'
        'It will be computed on the lot/serial number.')
    alert_time = fields.Integer(string='Alert Date',
        help='Number of days before the Expiration Date after which an alert should be'
        ' raised on the lot/serial number. It will be computed on the lot/serial number.')

    def write(self, vals):
        if vals.get('tracking') == 'none':
            vals['use_expiration_date'] = False
        return super().write(vals)

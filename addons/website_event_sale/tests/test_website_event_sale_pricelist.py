# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.fields import Command
from odoo.tests import tagged

from odoo.addons.website_event_sale.tests.common import TestWebsiteEventSaleCommon
from odoo.addons.website_sale.controllers.main import WebsiteSale
from odoo.addons.website_sale.tests.common import MockRequest


@tagged('post_install', '-at_install')
class TestWebsiteEventPriceList(TestWebsiteEventSaleCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.WebsiteSaleController = WebsiteSale()

    def test_pricelist_different_currency(self):
        self.env['product.pricelist'].search([('id', '!=', self.pricelist.id)]).action_archive()
        self.pricelist.write({
            'currency_id': self.env.company.currency_id.id,
            'item_ids': [Command.clear()],
            'name': 'No discount',
        })
        so_line = self.env['sale.order.line'].create({
            'event_id': self.event.id,
            'event_ticket_id': self.ticket.id,
            'name': self.event.name,
            'order_id': self.empty_cart.id,
            'product_id': self.ticket.product_id.id,
            'product_uom_qty': 1,
        })
        self.assertEqual(so_line.price_unit_discounted_taxexc, 100)

        # set pricelist to 10% - without discount
        pl2 = self.pricelist.copy({
            'currency_id': self.currency_test.id,
            'item_ids': [(5, 0, 0), (0, 0, {
                'applied_on': '3_global',
                'compute_price': 'percentage',
                'percent_price': 10,
            })],
            'name': 'Percentage Discount',
            'selectable': True,
        })
        with MockRequest(self.env, website=self.website, sale_order_id=self.empty_cart.id) as req:
            self.assertEqual(req.pricelist, self.pricelist)
            self.WebsiteSaleController.pricelist_change(pl2)
            self.assertEqual(so_line.price_unit_discounted_taxexc, 900, 'Incorrect amount based on the pricelist and its currency.')


@tagged('post_install', '-at_install')
class TestEventSalePricelistItemWarning(TestWebsiteEventSaleCommon):
    """UI warning on pricelist items whose min. quantity skips event tickets."""

    def test_min_qty_global_item_warns(self):
        """A global item with positive min. quantity warns it skips tickets."""
        item = self.env['product.pricelist.item'].new({
            'applied_on': '3_global',
            'min_quantity': 2,
        })
        res = item._onchange_event_sale_warning()
        self.assertIn('will not be applied', res['warning']['message'])

    def test_min_qty_event_template_item_warns(self):
        """A product item targeting an event product template warns."""
        item = self.env['product.pricelist.item'].new({
            'applied_on': '1_product',
            'min_quantity': 1,
            'product_tmpl_id': self.product_event.product_tmpl_id.id,
        })
        res = item._onchange_event_sale_warning()
        self.assertIn('cannot be applied', res['warning']['message'])

    def test_min_qty_event_variant_item_warns(self):
        """A variant item targeting an event product variant warns."""
        item = self.env['product.pricelist.item'].new({
            'applied_on': '0_product_variant',
            'min_quantity': 1,
            'product_id': self.product_event.id,
        })
        res = item._onchange_event_sale_warning()
        self.assertIn('cannot be applied', res['warning']['message'])

    def test_min_qty_zero_no_warning(self):
        """No warning without a positive min. quantity (boundary case)."""
        item = self.env['product.pricelist.item'].new({
            'applied_on': '3_global',
            'min_quantity': 0,
        })
        self.assertIsNone(item._onchange_event_sale_warning())

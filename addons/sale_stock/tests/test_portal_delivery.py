from odoo.fields import Command
from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestPortalDeliveryReports(HttpCase):
    """Token/access gates of the portal delivery and return-label PDFs."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        partner = cls.env['res.partner'].create({
            'name': 'Portal delivery customer',
            'email': 'portal.delivery@example.com',
        })
        product = cls.env['product.product'].create({
            'name': 'Shippable widget',
            'type': 'consu',
            'list_price': 10,
        })
        cls.order = cls.env['sale.order'].create({
            'partner_id': partner.id,
            'line_ids': [Command.create({
                'product_id': product.id,
                'product_uom_qty': 2,
            })],
        })
        cls.order.action_confirm()
        cls.picking = cls.order.picking_ids[:1]
        cls.token = cls.order._portal_ensure_token()

    def test_delivery_pdf_with_valid_token(self):
        """A valid sale token opens the delivery slip as PDF."""
        self.assertTrue(self.picking)
        res = self.url_open(
            f'/my/picking/pdf/{self.picking.id}?access_token={self.token}',
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers.get('Content-Type'), 'application/pdf')

    def test_delivery_pdf_without_token_is_denied(self):
        """The public visitor without a token cannot read the slip."""
        res = self.url_open(f'/my/picking/pdf/{self.picking.id}')
        self.assertIn(res.status_code, (403, 404))

    def test_delivery_pdf_with_wrong_token_is_denied(self):
        """A forged token does not grant access (consteq gate)."""
        res = self.url_open(
            f'/my/picking/pdf/{self.picking.id}?access_token=forged-token',
        )
        self.assertIn(res.status_code, (403, 404))

    def test_return_label_pdf_with_valid_token(self):
        """The return-label route honors the same token gate."""
        res = self.url_open(
            f'/my/picking/return/pdf/{self.picking.id}'
            f'?access_token={self.token}',
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers.get('Content-Type'), 'application/pdf')

    def test_missing_picking_is_not_found(self):
        """A nonexistent picking id resolves to not-found, not a crash."""
        res = self.url_open(
            f'/my/picking/pdf/99999999?access_token={self.token}',
        )
        self.assertIn(res.status_code, (403, 404))

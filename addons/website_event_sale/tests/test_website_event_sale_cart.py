from datetime import datetime, timedelta

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import Form, tagged

from odoo.addons.website_event_sale.tests.common import TestWebsiteEventSaleCommon
from odoo.addons.website_sale.tests.test_website_sale_cart_abandoned import (
    TestWebsiteSaleCartAbandonedCommon,
)


@tagged('post_install', '-at_install')
class TestWebsiteEventSaleCart(TestWebsiteEventSaleCommon, TestWebsiteSaleCartAbandonedCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.website.write({
            'send_abandoned_cart_email': True,
            'cart_abandoned_delay': 1.0,  # 1 hour
        })
        cls.website.send_abandoned_cart_email_activation_time -= timedelta(weeks=1)

        cls.partner_admin = cls.env.ref('base.partner_admin')
        if not cls.partner_admin.email:
            cls.partner_admin.email = 'base@partner.admin'

    def test_sold_out_event_cart_reminder(self):
        """Check that abandoned cart emails aren't sent for sold out tickets."""
        cart1, cart2 = self.env['sale.order'].create([{
            'partner_id': partner.id,
            'website_id': self.website.id,
            'date_order': datetime.now() - timedelta(hours=2),
        } for partner in (self.partner_admin, self.partner_portal)])

        self.ticket.write({
            'seats_limited': True,
            'seats_max': 1,
        })

        create_order_line = [Command.create({
            'product_id': self.product_event.id,
            'event_id': self.event.id,
            'event_ticket_id': self.ticket.id,
        })]
        cart1.line_ids = create_order_line
        cart2.line_ids = create_order_line
        self.assertTrue(
            self.send_mail_patched(cart1.id),
            "Abandoned cart email should be sent for availlable tickets",
        )

        # Create registrations & confirm first order
        editor = Form(self.env['registration.editor'].with_context(default_sale_order_id=cart1.id))
        editor.save().action_make_registration()
        cart1.action_confirm()
        # command-created records won't trigger a recompute until flush
        self.env.flush_all()
        self.assertEqual(self.ticket.seats_available, 0)
        self.assertFalse(
            self.send_mail_patched(cart2.id),
            "Abandoned cart email should not be sent when ticket has no seats available",
        )

        # Reset sent state, increase seat limit, and try again
        cart2.cart_recovery_email_sent = False
        self.ticket.seats_max = 2
        self.assertTrue(
            self.send_mail_patched(cart2.id),
            "Abandoned cart email can be sent after increasing seat count",
        )


@tagged('post_install', '-at_install')
class TestWebsiteEventSaleCartSeats(TestWebsiteEventSaleCommon):
    """Seat availability and event-ticket guards on cart quantity updates."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.cart = cls.empty_cart
        cls.partner_admin = cls.env.ref('base.partner_admin')

    def test_cart_add_unknown_ticket_raises(self):
        """Adding a nonexistent ticket id to the cart raises UserError."""
        with self.assertRaises(UserError):
            self.cart._cart_add(
                self.product_event.id, 1, event_ticket_id=-1,
            )

    def test_cart_add_unknown_slot_raises(self):
        """Adding a valid ticket with a nonexistent slot id raises UserError."""
        with self.assertRaises(UserError):
            self.cart._cart_add(
                self.product_event.id, 1,
                event_ticket_id=self.ticket.id, event_slot_id=-1,
            )

    def test_cart_add_product_ticket_mismatch_raises(self):
        """The provided product must match the ticket's product."""
        other_product = self.env['product.product'].create({
            'name': 'Not an event product',
            'type': 'service',
            'list_price': 10,
        })
        with self.assertRaises(UserError):
            self.cart._cart_add(
                other_product.id, 1, event_ticket_id=self.ticket.id,
            )

    def test_cart_add_sold_out_ticket_blocked(self):
        """No quantity is added and a sold-out warning is returned."""
        ticket = self.env['event.event.ticket'].create({
            'event_id': self.event.id,
            'name': 'Limited',
            'product_id': self.product_event.id,
            'price': 100,
            'seats_max': 1,
            'seats_limited': True,
        })
        self.env['event.registration'].create({
            'event_id': self.event.id,
            'event_ticket_id': ticket.id,
            'partner_id': self.partner_admin.id,
            'state': 'open',
        })
        self.env.flush_all()
        self.assertEqual(ticket.seats_available, 0)

        res = self.cart._cart_add(
            self.product_event.id, 1, event_ticket_id=ticket.id,
        )
        self.assertEqual(res['quantity'], 0)
        self.assertIn('sold out', res['warning'])

    def test_cart_add_clamped_to_available_seats(self):
        """Requested quantity is clamped to the remaining seats."""
        ticket = self.env['event.event.ticket'].create({
            'event_id': self.event.id,
            'name': 'Limited',
            'product_id': self.product_event.id,
            'price': 100,
            'seats_max': 2,
            'seats_limited': True,
        })
        res = self.cart._cart_add(
            self.product_event.id, 5, event_ticket_id=ticket.id,
        )
        self.assertEqual(res['quantity'], 2)
        self.assertIn('only 2 seats', res['warning'])

    def test_cart_manual_quantity_raise_blocked(self):
        """Raising an event line quantity without ticket context is refused."""
        res_add = self.cart._cart_add(
            self.product_event.id, 1, event_ticket_id=self.ticket.id,
        )
        line = self.env['sale.order.line'].browse(res_add['line_id'])
        self.assertEqual(line.product_uom_qty, 1)

        res = self.cart._cart_update_line_quantity(line.id, 3)
        self.assertEqual(res['quantity'], 1)
        self.assertIn('cannot raise manually', res['warning'])
        self.assertEqual(line.product_uom_qty, 1)

    def test_cart_quantity_decrease_cancels_registrations(self):
        """Decreasing an event line quantity cancels the newest registrations."""
        res_add = self.cart._cart_add(
            self.product_event.id, 2, event_ticket_id=self.ticket.id,
        )
        line = self.env['sale.order.line'].browse(res_add['line_id'])
        reg_first, reg_second = self.env['event.registration'].create([
            {
                'event_id': self.event.id,
                'event_ticket_id': self.ticket.id,
                'partner_id': self.partner_admin.id,
                'sale_order_id': self.cart.id,
                'state': 'open',
            }
            for _dummy in range(2)
        ])

        self.cart._cart_update_line_quantity(line.id, 1)

        self.assertEqual(line.product_uom_qty, 1)
        self.assertNotEqual(reg_first.state, 'cancel')
        self.assertEqual(reg_second.state, 'cancel')

from odoo.exceptions import ValidationError
from odoo.tests import Form, tagged

from odoo.addons.event_product.tests.common import TestEventProductCommon


@tagged("post_install", "-at_install")
class TestEventProduct(TestEventProductCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.test_event = cls.env["event.event"].create(
            {
                "name": "TestEventProduct",
                "event_type_id": cls.event_type_tickets.id,
            }
        )

    def test_ensure_event_service_tracking(self):
        with self.assertRaises(ValidationError):
            self.event_product.service_tracking = "no"
        with self.assertRaises(ValidationError):
            with Form(self.event_product) as product_form:
                product_form.type = "consu"

    def test_ensure_event_type_ticket_service_tracking(self):
        """A product with a mismatched service_tracking must be rejected on
        the event.type.ticket side too, not only via product.product."""
        other_product = self.env["product.product"].create(
            {
                "name": "Not An Event Product",
                "list_price": 5,
                "type": "service",
                "service_tracking": "no",
            }
        )
        ticket_type = self.event_type_tickets.event_type_ticket_ids[0]
        with self.assertRaises(ValidationError):
            ticket_type.product_id = other_product.id

    def test_price_reduce_taxinc_recomputes_on_dependency_change(self):
        """Regression test: price_reduce_taxinc must stay in sync with its
        declared dependencies (price_reduce, product_id, product_id.taxes_id)."""
        ticket = self.test_event.event_ticket_ids[0]
        # Clear any tax the product picked up from company defaults on
        # creation, so the "no tax" baseline below is actually tax-free.
        ticket.product_id.taxes_id = [(6, 0, [])]
        self.assertEqual(ticket.price_reduce_taxinc, ticket.price_reduce)

        tax = self.env["account.tax"].create(
            {
                "name": "Test Tax 25%",
                "amount": 25.0,
                "amount_type": "percent",
                "type_tax_use": "sale",
            }
        )
        ticket.product_id.taxes_id = [(6, 0, [tax.id])]

        self.assertAlmostEqual(
            ticket.price_reduce_taxinc,
            ticket.price_reduce * 1.25,
            msg="price_reduce_taxinc did not recompute after product_id.taxes_id changed",
        )

    def test_registration_status_defaults_without_order(self):
        """event.registration._compute_registration_status must default
        sale_status to 'free' and state to 'open' when _has_order() is False."""
        registration = self.env["event.registration"].create(
            {
                "event_id": self.test_event.id,
            }
        )
        self.assertEqual(registration.sale_status, "free")
        self.assertEqual(registration.state, "open")

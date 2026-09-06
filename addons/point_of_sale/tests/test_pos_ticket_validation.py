from types import SimpleNamespace
from unittest.mock import patch

from odoo.tests import tagged

from odoo.addons.point_of_sale.controllers import main
from odoo.addons.point_of_sale.tests.common import TestPoSCommon
from odoo.addons.point_of_sale.tests.test_pos_invoice_guards import TestPosInvoiceGuards
from odoo.addons.portal.controllers import portal


@tagged("post_install", "-at_install")
class TestPosTicketValidation(TestPoSCommon):
    _make_order = TestPosInvoiceGuards._make_order

    def setUp(self):
        super().setUp()
        self.config = self.basic_config
        self.product = self.create_product("Ticket product", self.categ_basic, 100, 50)
        self._start_pos_session(self.cash_pm1, 0)
        self.partner = self.env.user.partner_id
        self.partner.write(
            {
                "name": "Invoice customer",
                "email": "customer@example.test",
                "street": "Test street",
                "city": "Test city",
                "zip": "10001",
                "country_id": self.env.ref("base.us").id,
                "state_id": self.env.ref("base.state_us_1").id,
                "phone": "5555555555",
            }
        )
        self.order = self._make_order("draft")
        self.order.add_payment(
            {
                "pos_order_id": self.order.id,
                "amount": 100,
                "payment_method_id": self.cash_pm1.id,
            }
        )
        self.order.action_pos_order_paid()

    def _submit_ticket(self, method="POST", **values):
        fake_request = SimpleNamespace(
            env=self.env,
            httprequest=SimpleNamespace(method=method),
            redirect=lambda url: ("redirect", url),
            render=lambda template, context: ("render", template, context),
        )
        invoice_fields = self.env["ir.model.fields"]._get(
            "account.move", "invoice_source_email"
        )
        partner_fields = self.env["ir.model.fields"]._get("res.partner", "phone")
        endpoint = main.PosController.show_ticket_validation_screen
        while hasattr(endpoint, "__wrapped__"):
            endpoint = endpoint.__wrapped__
        with (
            patch.object(main, "request", fake_request),
            patch.object(portal, "request", fake_request),
            patch.object(
                type(self.env["account.move"]),
                "get_invoice_localisation_fields_required_to_invoice",
                return_value=list(invoice_fields),
            ),
            patch.object(
                type(self.env["res.partner"]),
                "get_partner_localisation_fields_required_to_invoice",
                return_value=list(partner_fields),
            ),
        ):
            return endpoint(
                main.PosController(), access_token=self.order.access_token, **values
            )

    def test_connected_get_collects_required_invoice_fields(self):
        response = self._submit_ticket(method="GET")
        self.assertEqual(response[0], "render")
        self.assertFalse(self.order.account_move)

    def test_missing_extra_field_does_not_invoice_or_mutate_partner(self):
        response = self._submit_ticket(partner_phone="1234567890")
        self.assertEqual(response[0], "render")
        self.assertIn("invoice_source_email", response[2]["invalid_fields"])
        self.assertEqual(
            response[2]["extra_field_values"]["partner_phone"], "1234567890"
        )
        self.assertEqual(self.partner.phone, "5555555555")
        self.assertFalse(self.order.account_move)

    def test_connected_post_accepts_extra_fields_without_address_inputs(self):
        response = self._submit_ticket(
            partner_phone=self.partner.phone,
            invoice_invoice_source_email="customer@example.test",
        )
        self.assertEqual(response[0], "redirect")
        self.assertEqual(self.order.account_move.state, "posted")
        self.assertEqual(
            self.order.account_move.invoice_source_email, "customer@example.test"
        )

    def test_invalid_address_retains_invoice_input(self):
        response = self._submit_ticket(
            partner_phone=self.partner.phone,
            invoice_invoice_source_email="customer@example.test",
            email="invalid",
        )
        self.assertEqual(response[0], "render")
        self.assertIn("email", response[2]["invalid_fields"])
        self.assertEqual(
            response[2]["extra_field_values"]["invoice_invoice_source_email"],
            "customer@example.test",
        )
        self.assertFalse(self.order.account_move)

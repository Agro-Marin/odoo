import json

from odoo.tests import HttpCase, tagged

from odoo.addons.payment import utils as payment_utils


@tagged("post_install", "-at_install")
class TestDonationPortal(HttpCase):
    """Public donation form and transaction route guards."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.provider = cls.env.ref("payment.payment_provider_transfer")
        cls.provider.write({"state": "enabled", "is_published": True})
        cls.method = cls.provider.payment_method_ids[:1]
        cls.currency = cls.env.company.currency_id
        cls.country = cls.env.ref("base.mx")

    def _donation_rpc(self, minimum, params):
        payload = {"jsonrpc": "2.0", "method": "call", "params": params, "id": 1}
        res = self.url_open(
            f"/donation/transaction/{minimum}",
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(res.status_code, 200)
        return res.json()

    def _base_params(self, amount):
        public_partner = self.env.ref("base.public_user").partner_id
        return {
            "amount": amount,
            "currency_id": self.currency.id,
            "partner_id": public_partner.id,
            "access_token": payment_utils.generate_access_token(
                public_partner.id,
                amount,
                self.currency.id,
                env=self.env,
            ),
            "provider_id": self.provider.id,
            "payment_method_id": self.method.id,
            "token_id": None,
            "flow": "direct",
            "tokenization_requested": False,
            "landing_route": "/donation/pay",
            "partner_details": {
                "name": "Generous Donor",
                "email": "donor@example.com",
                "country_id": self.country.id,
            },
            "donation_comment": "For the cause",
            "donation_recipient_email": "treasury@example.com",
        }

    def test_donation_form_renders_for_public(self):
        """The public donation page renders with the default amount."""
        res = self.url_open("/donation/pay")
        self.assertEqual(res.status_code, 200)
        self.assertIn("donation", res.text.lower())

    def test_donation_below_minimum_is_rejected(self):
        """An amount under the snippet minimum raises the validation."""
        reply = self._donation_rpc(50, self._base_params(10.0))
        self.assertIn("error", reply)
        self.assertIn(
            "must be at least",
            reply["error"]["data"]["message"],
        )

    def test_donation_requires_name(self):
        """A public donor without name is rejected."""
        params = self._base_params(30.0)
        params["partner_details"]["name"] = ""
        reply = self._donation_rpc(0, params)
        self.assertIn("Name is required", reply["error"]["data"]["message"])

    def test_donation_requires_email(self):
        """A public donor without email is rejected."""
        params = self._base_params(30.0)
        params["partner_details"]["email"] = ""
        reply = self._donation_rpc(0, params)
        self.assertIn("Email is required", reply["error"]["data"]["message"])

    def test_donation_requires_country(self):
        """A public donor without country is rejected."""
        params = self._base_params(30.0)
        params["partner_details"]["country_id"] = False
        reply = self._donation_rpc(0, params)
        self.assertIn("Country is required", reply["error"]["data"]["message"])

    def test_public_donation_creates_transaction(self):
        """The public flow creates a donation tx carrying the donor details."""
        reply = self._donation_rpc(0, self._base_params(40.0))
        self.assertNotIn("error", reply, reply.get("error"))
        self.assertIn("reference", reply["result"])

        tx = (
            self.env["payment.transaction"]
            .sudo()
            .search(
                [("reference", "=", reply["result"]["reference"])],
            )
        )
        self.assertTrue(tx.is_donation)
        self.assertEqual(tx.amount, 40.0)
        self.assertEqual(tx.partner_name, "Generous Donor")
        self.assertEqual(tx.partner_email, "donor@example.com")
        self.assertEqual(tx.partner_country_id, self.country)

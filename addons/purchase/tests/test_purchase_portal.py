from datetime import date

from odoo.fields import Command
from odoo.tests import tagged

from odoo.addons.base.tests.common import HttpCaseWithUserPortal


@tagged("post_install", "-at_install")
class TestPurchasePortalRoutes(HttpCaseWithUserPortal):
    """Vendor portal routes: token gate, acknowledge, date updates, EDI."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.vendor = cls.partner_portal
        product = cls.env["product.product"].create(
            {"name": "Portal bolts", "type": "consu", "list_price": 4.0}
        )
        cls.order = cls.env["purchase.order"].create(
            {
                "partner_id": cls.vendor.id,
                "line_ids": [
                    Command.create({"product_id": product.id, "product_qty": 5})
                ],
            }
        )
        cls.token = cls.order._portal_ensure_token()
        cls.line = cls.order.line_ids[:1]

    def test_order_page_without_token_redirects_home(self):
        """The public visitor without a token never sees the order page."""
        res = self.url_open(f"/my/purchase/{self.order.id}")
        # /my itself needs a session, so the public visitor chains to login;
        # the contract is that the document is not served.
        self.assertNotIn(f"/my/purchase/{self.order.id}", res.url)
        self.assertNotIn(self.order.name, res.text)

    def test_order_page_with_token_renders(self):
        """A valid token shows the vendor the order page."""
        res = self.url_open(f"/my/purchase/{self.order.id}?access_token={self.token}")
        self.assertEqual(res.status_code, 200)
        self.assertIn(self.order.name, res.text)

    def test_acknowledge_flags_order_and_redirects(self):
        """Acknowledging marks the order and redirects with the banner."""
        self.assertFalse(self.order.acknowledged)
        res = self.url_open(
            f"/my/purchase/{self.order.id}?access_token={self.token}&acknowledge=1"
        )
        self.assertIn("message=ack_ok", res.url)
        self.assertTrue(self.order.acknowledged)

    def test_update_line_date_from_portal(self):
        """The vendor can push a new scheduled date on a line."""
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "id": 1,
            "params": {
                "access_token": self.token,
                str(self.line.id): "2026-09-15",
            },
        }
        res = self.opener.post(
            self.base_url() + f"/my/purchase/{self.order.id}/update",
            json=payload,
        )
        self.assertEqual(res.status_code, 200)
        self.env.invalidate_all()
        self.assertEqual(self.line.date_commitment.date(), date(2026, 9, 15))

    def test_update_line_ignores_invalid_date(self):
        """A malformed date leaves the scheduled date untouched."""
        before = self.line.date_commitment
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "id": 1,
            "params": {
                "access_token": self.token,
                str(self.line.id): "not-a-date",
            },
        }
        self.opener.post(
            self.base_url() + f"/my/purchase/{self.order.id}/update",
            json=payload,
        )
        self.env.invalidate_all()
        self.assertEqual(self.line.date_commitment, before)

    def test_download_edi_serves_xml(self):
        """With the fork's default builder the EDI download serves XML."""
        res = self.url_open(
            f"/my/purchase/{self.order.id}/download_edi?access_token={self.token}"
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers.get("Content-Type"), "text/xml")
        self.assertIn("attachment", res.headers.get("Content-Disposition", ""))

    def test_vendor_portal_lists_render(self):
        """The vendor sees the RFQ and order lists once logged in."""
        self.authenticate("portal", "portal")
        res_rfq = self.url_open("/my/rfq")
        self.assertEqual(res_rfq.status_code, 200)
        res_orders = self.url_open("/my/purchase")
        self.assertEqual(res_orders.status_code, 200)

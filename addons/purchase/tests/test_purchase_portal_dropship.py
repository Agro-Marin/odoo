from odoo.fields import Command
from odoo.tests import tagged

from odoo.addons.base.tests.common import HttpCaseWithUserPortal


@tagged("post_install", "-at_install")
class TestPurchasePortalDropshipAddress(HttpCaseWithUserPortal):
    """On a dropship order the vendor ships to a third party. That address is on
    both PDFs (`report/purchase_order_templates.xml:12`,
    `report/purchase_quotation_templates.xml:14`) but was missing from the portal
    page, so the only way to read it was to open or download the PDF.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.end_customer = cls.env["res.partner"].create(
            {
                "name": "Rancho El Tepeyac",
                "street": "Camino a la Presa 4120",
                "city": "Culiacan",
            }
        )
        product = cls.env["product.product"].create(
            {"name": "Dropship seed", "type": "consu", "list_price": 9.0}
        )
        cls.dropship_order, cls.plain_order = cls.env["purchase.order"].create(
            [
                {
                    "partner_id": cls.partner_portal.id,
                    "dest_address_id": dest,
                    "line_ids": [
                        Command.create({"product_id": product.id, "product_qty": 2})
                    ],
                }
                for dest in (cls.end_customer.id, False)
            ]
        )

    def _portal_page(self, order):
        token = order._portal_ensure_token()
        response = self.url_open(f"/my/purchase/{order.id}?access_token={token}")
        self.assertEqual(response.status_code, 200)
        return response.text

    def test_dropship_order_shows_the_shipping_address(self):
        page = self._portal_page(self.dropship_order)
        self.assertIn("Camino a la Presa 4120", page)
        self.assertIn("Rancho El Tepeyac", page)

    def test_plain_order_shows_no_shipping_address_block(self):
        self.assertNotIn("Shipping address", self._portal_page(self.plain_order))

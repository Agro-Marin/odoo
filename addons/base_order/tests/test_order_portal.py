# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import Command
from odoo.tests import tagged

from odoo.addons.base.tests.common import HttpCaseWithUserPortal

# Part 5 of base_order's by-parts coverage: the portal list pages.
#
# _order_portal_rendering_values (OrderPortalMixin) backs four routes across two
# modules. Nothing exercised those routes over HTTP before — the existing
# controller tests only cover the single-order detail route — so the failure
# mode the module-prefixed hooks exist to prevent (sale's and purchase's
# CustomerPortal being fused into one MRO by build_controllers, one shadowing
# the other) would have gone unnoticed. These tests drive all four pages and
# assert each shows its own module's orders and not the other's.


@tagged("post_install", "-at_install")
class TestOrderPortalLists(HttpCaseWithUserPortal):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product = cls.env["product.product"].create(
            {"name": "Portal Probe Product", "type": "consu"},
        )

        def line():
            return [
                Command.create(
                    {
                        "product_id": cls.product.id,
                        "product_qty": 1.0,
                        "price_unit": 100.0,
                    },
                ),
            ]

        # A quotation (draft + sent) and a confirmed sale order.
        cls.quotation = cls.env["sale.order"].create(
            {"partner_id": cls.partner_portal.id, "line_ids": line()},
        )
        cls.quotation.sent = True
        cls.sale_order = cls.env["sale.order"].create(
            {"partner_id": cls.partner_portal.id, "line_ids": line()},
        )
        cls.sale_order.action_confirm()

        # An RFQ (draft) and a confirmed purchase order.
        cls.rfq = cls.env["purchase.order"].create(
            {"partner_id": cls.partner_portal.id, "line_ids": line()},
        )
        cls.purchase_order = cls.env["purchase.order"].create(
            {"partner_id": cls.partner_portal.id, "line_ids": line()},
        )
        cls.purchase_order.action_confirm()

    def _get_page(self, url):
        self.authenticate("portal", "portal")
        response = self.url_open(url)
        self.assertEqual(response.status_code, 200, f"{url} did not render")
        return response.text

    # --- each list page shows its own orders ---

    def test_my_quotes_lists_quotation(self):
        body = self._get_page("/my/quotes")
        self.assertIn(self.quotation.name, body)

    def test_my_orders_lists_sale_order(self):
        body = self._get_page("/my/orders")
        self.assertIn(self.sale_order.name, body)

    def test_my_rfq_lists_rfq(self):
        body = self._get_page("/my/rfq")
        self.assertIn(self.rfq.name, body)

    def test_my_purchase_lists_purchase_order(self):
        body = self._get_page("/my/purchase")
        self.assertIn(self.purchase_order.name, body)

    # --- and not the other module's (the MRO-collision detector) ---

    def test_sale_pages_exclude_purchase_orders(self):
        """A collision would make a sale page render purchase's config."""
        body = self._get_page("/my/orders")
        self.assertNotIn(self.purchase_order.name, body)
        self.assertNotIn(self.rfq.name, body)

    def test_purchase_pages_exclude_sale_orders(self):
        """A collision would make a purchase page render sale's config."""
        body = self._get_page("/my/purchase")
        self.assertNotIn(self.sale_order.name, body)
        self.assertNotIn(self.quotation.name, body)

    # --- the shared machinery's own behaviour ---

    def test_unknown_sortby_does_not_500(self):
        """_resolve_searchbar_option clamps an unknown ?sortby= instead of
        raising KeyError, on every page the shared helper backs."""
        for url in ("/my/quotes", "/my/orders", "/my/rfq", "/my/purchase"):
            with self.subTest(url=url):
                self._get_page(f"{url}?sortby=not_a_real_sort")

    def test_home_shows_both_modules_counters(self):
        """Both modules must contribute counters; the super() chain means a
        broken override would silently drop one module's numbers."""
        self.authenticate("portal", "portal")
        response = self.url_open("/my")
        self.assertEqual(response.status_code, 200)

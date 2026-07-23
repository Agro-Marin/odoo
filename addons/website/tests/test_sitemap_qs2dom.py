# Part of Odoo. See LICENSE file for full copyright and licensing details.
from odoo.fields import Domain
from odoo.tests import BaseCase, tagged

from odoo.addons.website.models.ir_http import sitemap_qs2dom


@tagged("at_install", "standard")
class TestSitemapQs2Dom(BaseCase):
    """Pin sitemap_qs2dom's filtering semantics (it historically leaned on
    unittest.util.unorderable_list_difference for its mutation side effect;
    the reimplementation must keep one-removal-per-route-segment behavior)."""

    def test_no_qs_matches_everything(self):
        self.assertEqual(sitemap_qs2dom(None, "/shop"), Domain.TRUE)
        self.assertEqual(sitemap_qs2dom("", "/shop"), Domain.TRUE)

    def test_qs_contained_in_route_matches_everything(self):
        # case-insensitive containment: the qs targets the route itself
        self.assertEqual(sitemap_qs2dom("shop", "/shop/category"), Domain.TRUE)
        self.assertEqual(sitemap_qs2dom("SHOP", "/shop/category"), Domain.TRUE)

    def test_single_needle_builds_ilike(self):
        dom = sitemap_qs2dom("/x", "/shop", "name")
        self.assertEqual(dom, Domain("name", "ilike", "x"))
        # route segments present in the qs are dropped, one occurrence each;
        # the leftover duplicate is the needle (the doc's historical example).
        dom = sitemap_qs2dom("shop/product/product", "/shop/product", "name")
        self.assertEqual(dom, Domain("name", "ilike", "product"))

    def test_multiple_needles_match_nothing(self):
        self.assertEqual(sitemap_qs2dom("/a/b", "/shop"), Domain.FALSE)

    def test_custom_field(self):
        dom = sitemap_qs2dom("chair", "/shop", "seo_name")
        self.assertEqual(dom, Domain("seo_name", "ilike", "chair"))

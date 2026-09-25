from datetime import datetime, timedelta

from freezegun import freeze_time

from odoo.api import Environment
from odoo.tests import tagged

from odoo.addons.base.tests.common import BaseCommon
from odoo.addons.http_routing.tests.common import MockRequest


@tagged("post_install", "-at_install")
class TestWebsiteSequence(BaseCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.website = cls.env.ref("website.default_website")
        cls.public_user = cls.env.ref("base.public_user")

        ProductTemplate = cls.env["product.template"]
        # the products this class orders sit above every existing sequence, so
        # moving one up or down only ever meets another of them
        cls.base = (
            ProductTemplate.with_context(active_test=False)
            .search([], order="website_sequence DESC", limit=1)
            .website_sequence
            or 0
        )
        cls.product_tmpls = cls.p1, cls.p2, cls.p3, cls.p4 = ProductTemplate.create(
            [
                {"name": "First Product", "website_sequence": cls.base + 100},
                {"name": "Second Product", "website_sequence": cls.base + 180},
                {"name": "Third Product", "website_sequence": cls.base + 225},
                {"name": "Last Product", "website_sequence": cls.base + 250},
            ]
        )

    def _sequence_bounds(self):
        ProductTemplate = self.env["product.template"]
        lowest = ProductTemplate.search([], order="website_sequence ASC", limit=1)
        highest = ProductTemplate.search([], order="website_sequence DESC", limit=1)
        return lowest.website_sequence, highest.website_sequence

    def get_product_sort_mapping(self, label):
        context = dict(self.env.context, website_id=self.website.id, lang="en_US")
        env = Environment(self.env.cr, self.public_user.id, context)
        with MockRequest(env, website=self.website.with_env(env)) as req:
            product_sort_mapping = req.env["website"]._selection_product_sorts()
            return next(k for k, v in product_sort_mapping if v == label)

    def get_sorted_products(self, order, products=None):
        products = products or self.product_tmpls
        return products.search(
            [("id", "in", products.ids)],
            order=order,
        )

    def assertProductOrdering(self, products, order):
        expected = self.get_sorted_products(order, products=products)
        self.assertSequenceEqual(
            products, expected, f"Products should be ordered on '{order}'"
        )

    def test_01_website_sequence(self):
        sequence_order = self.get_product_sort_mapping("Featured")
        self.assertProductOrdering(
            self.p1 + self.p2 + self.p3 + self.p4, sequence_order
        )
        self.p2.set_sequence_down()
        self.assertProductOrdering(
            self.p1 + self.p3 + self.p2 + self.p4, sequence_order
        )
        self.p4.set_sequence_up()
        self.assertProductOrdering(
            self.p1 + self.p3 + self.p4 + self.p2, sequence_order
        )
        lowest, _highest = self._sequence_bounds()
        self.p2.set_sequence_top()
        self.assertEqual(self.p2.website_sequence, lowest - 5)
        self.assertProductOrdering(
            self.p2 + self.p1 + self.p3 + self.p4, sequence_order
        )
        _lowest, highest = self._sequence_bounds()
        self.p1.set_sequence_bottom()
        self.assertEqual(self.p1.website_sequence, highest + 5)
        self.assertProductOrdering(
            self.p2 + self.p3 + self.p4 + self.p1, sequence_order
        )

        current_products = self.get_sorted_products(sequence_order)
        self.assertEqual(
            current_products.mapped("website_sequence")[1:],
            [self.base + 180, self.base + 225, self.base + 230],
            "Wrong sequence order (2)",
        )

        self.p2.website_sequence = min(self._sequence_bounds()[0], 1)
        self.p3.set_sequence_top()
        self.assertEqual(self.p3.website_sequence, self.p2.website_sequence - 5)
        self.assertLess(
            self.p3.website_sequence, 0, "`website_sequence` should go below 0"
        )

        new_product = self.env["product.template"].create(
            {
                "name": "Last Newly Created Product",
            }
        )
        current_products += new_product

        self.assertEqual(
            self.get_sorted_products(sequence_order, current_products)[-1],
            new_product,
            "New product should be last",
        )

    def test_02_newest_arrivals(self):
        def toggle_publish(products, delta=timedelta(seconds=5)):
            publish_date = datetime.now()
            for product in products:
                publish_date += delta
                with freeze_time(publish_date):
                    product.website_publish_button()
                    product.flush_recordset()

        newest_arrival_order = self.get_product_sort_mapping("Newest Arrivals")

        toggle_publish(self.product_tmpls)
        target = self.product_tmpls[::-1]
        self.assertTrue(all(self.product_tmpls.mapped("is_published")))
        self.assertProductOrdering(target, newest_arrival_order)

        publish_dates = self.product_tmpls.mapped("publish_date")
        toggle_publish(self.product_tmpls)
        self.assertFalse(any(self.product_tmpls.mapped("is_published")))
        self.assertSequenceEqual(
            self.product_tmpls.mapped("publish_date"),
            publish_dates,
            "Unpublishing should not affect publishing date",
        )

        toggle_publish(self.p2, delta=timedelta(days=1))
        self.assertEqual(
            self.get_sorted_products(newest_arrival_order)[0],
            self.p2,
            "Most recently published product should appear first",
        )

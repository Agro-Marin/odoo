import functools
import logging
import random
import time

from odoo.fields import Command
from odoo.tests import tagged
from odoo.tests.common import users, warmup

from odoo.addons.base.tests.common import TransactionCaseWithUserDemo

_logger = logging.getLogger(__name__)


def prepare(func, /):
    @functools.wraps(func)
    def test_func(self):
        _ = self.env.company.country_id.code
        return func(self)

    return test_func


@tagged("so_batch_perf")
class TestPERF(TransactionCaseWithUserDemo):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ENTITIES = 50

        cls.products = cls.env["product.product"].create(
            [
                {
                    "name": "Product %s" % i,
                    "list_price": 1 + 10 * i,
                    "type": "service",
                }
                for i in range(10)
            ]
        )

        cls.partners = cls.env["res.partner"].create(
            [
                {
                    "name": "Partner %s" % i,
                }
                for i in range(cls.ENTITIES)
            ]
        )

        cls.salesmans = cls.env.ref("base.user_admin") | cls.user_demo

        cls.env.flush_all()

    @users("admin")
    @warmup
    @prepare
    def test_empty_sale_order_creation_perf(self):
        with self.assertQueryCount(admin=34):
            self.env["sale.order"].create(
                {
                    "partner_id": self.partners[0].id,
                    "user_id": self.salesmans[0].id,
                }
            )

    @users("admin")
    @warmup
    @prepare
    def test_empty_sales_orders_batch_creation_perf(self):
        with self.assertQueryCount(admin=39):
            self.env["sale.order"].create(
                [
                    {
                        "partner_id": self.partners[0].id,
                        "user_id": self.salesmans[0].id,
                    }
                    for i in range(2)
                ]
            )

    @users("admin")
    @warmup
    @prepare
    def test_dummy_sales_orders_batch_creation_perf(self):
        with self.assertQueryCount(admin=44):
            self.env["sale.order"].create(
                [
                    {
                        "partner_id": self.partners[0].id,
                        "user_id": self.salesmans[0].id,
                        "line_ids": [
                            (0, 0, {"display_type": "line_note", "name": "NOTE"}),
                            (0, 0, {"display_type": "line_section", "name": "SECTION"}),
                        ],
                    }
                    for i in range(2)
                ]
            )

    @users("admin")
    @warmup
    @prepare
    def test_light_sales_orders_batch_creation_perf_without_taxes(self):
        self.env["res.country"].search([]).mapped("code")
        self.products[0].taxes_id = [Command.set([])]
        with self.assertQueryCount(admin=53):
            self.env["sale.order"].create(
                [
                    {
                        "partner_id": self.partners[0].id,
                        "user_id": self.salesmans[0].id,
                        "line_ids": [
                            (0, 0, {"display_type": "line_note", "name": "NOTE"}),
                            (0, 0, {"display_type": "line_section", "name": "SECTION"}),
                            (0, 0, {"product_id": self.products[0].id}),
                        ],
                    }
                    for i in range(2)
                ]
            )

    @users("admin")
    @warmup
    def __test_light_sales_orders_batch_creation_perf(self):
        with self.assertQueryCount(admin=70):
            self.env["sale.order"].create(
                [
                    {
                        "partner_id": self.partners[0].id,
                        "user_id": self.salesmans[0].id,
                        "line_ids": [
                            (0, 0, {"display_type": "line_note", "name": "NOTE"}),
                            (0, 0, {"display_type": "line_section", "name": "SECTION"}),
                            (0, 0, {"product_id": self.products[0].id}),
                        ],
                    }
                    for i in range(2)
                ]
            )

    @users("admin")
    @warmup
    def __test_complex_sales_orders_batch_creation_perf(self):
        self._test_complex_sales_orders_batch_creation_perf(1504)

    def _test_complex_sales_orders_batch_creation_perf(self, query_count):
        MSG = "Model %s, %i records, %s, time %.2f"

        vals_list = [
            {
                "partner_id": self.partners[i].id,
                "user_id": self.salesmans[i % 2].id,
                "line_ids": [(0, 0, {"display_type": "line_note", "name": "NOTE"})]
                + [(0, 0, {"product_id": product.id}) for product in self.products],
            }
            for i in range(self.ENTITIES)
        ]

        with self.assertQueryCount(admin=query_count):
            t0 = time.time()
            self.env["sale.order"].create(vals_list)
            t1 = time.time()
            _logger.info(MSG, "sale.order", self.ENTITIES, "BATCH", t1 - t0)
            self.env.cr.flush()
            _logger.info(MSG, "sale.order", self.ENTITIES, "FLUSH", time.time() - t1)

    @users("admin")
    @warmup
    def __test_randomized_solines_qties(self):
        vals_list = [
            {
                "partner_id": self.partners[i].id,
                "user_id": self.salesmans[i % 2].id,
                "line_ids": [(0, 0, {"display_type": "line_note", "name": "NOTE"})]
                + [
                    (0, 0, {"product_id": product.id, "product_qty": random.random()})
                    for product in self.products
                ],
            }
            for i in range(self.ENTITIES)
        ]

        with self.assertQueryCount(admin=1593):
            self.env["sale.order"].create(vals_list)

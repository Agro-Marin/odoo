import gc

from odoo import Command
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestMrpOrderpointBatch(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.env.company.id)], limit=1
        )
        cls.warehouse.manufacture_to_resupply = True
        cls.manufacture_rule = cls.warehouse.manufacture_pull_id
        cls.manufacture_route = cls.manufacture_rule.route_id
        cls.component = cls.env["product.product"].create(
            {"name": "Batch component", "is_storable": True}
        )
        cls.dozen = cls.env.ref("uom.product_uom_dozen")

    def make_products(self, count, with_bom):
        products = self.env["product.product"].create(
            [
                {
                    "name": "Batch %s %s" % ("made" if with_bom else "plain", index),
                    "is_storable": True,
                }
                for index in range(count)
            ]
        )
        if with_bom:
            self.env["mrp.bom"].create(
                [
                    {
                        "product_tmpl_id": product.product_tmpl_id.id,
                        "product_qty": 1.0,
                        "product_uom_id": self.dozen.id,
                        "type": "normal",
                        "bom_line_ids": [
                            Command.create(
                                {"product_id": self.component.id, "product_qty": 1}
                            )
                        ],
                    }
                    for product in products
                ]
            )
        return products

    def make_orderpoints(self, products, **values):
        return self.env["stock.warehouse.orderpoint"].create(
            [
                {
                    "product_id": product.id,
                    "location_id": self.warehouse.lot_stock_id.id,
                    "product_min_qty": 5.0,
                    "product_max_qty": 10.0,
                    **values,
                }
                for product in products
            ]
        )

    def statements(self, orderpoints, reader):
        # The transaction holds derived environments weakly, so whether their
        # cached `company`/`companies` survive to the next measurement is the
        # garbage collector's call: one collection between the two sizes made
        # it 14 against 13. Both start cold, ormcaches included, so both pay
        # the same misses.
        self.env.flush_all()
        self.env.invalidate_all()
        self.env.registry.clear_all_caches()
        gc.collect()
        orderpoints = orderpoints.browse(orderpoints.ids)
        before = self.env.cr.sql_statement_count
        result = reader(orderpoints)
        return self.env.cr.sql_statement_count - before, result

    def rule_ids_statements(self, pairs):
        made = self.make_products(pairs, with_bom=True)
        plain = self.make_products(pairs, with_bom=False)
        count, orderpoints = self.statements(
            self.make_orderpoints(made | plain),
            lambda orderpoints: orderpoints.filtered(
                lambda orderpoint: self.manufacture_rule in orderpoint.rule_ids
            ),
        )
        self.assertEqual(orderpoints.product_id, made)
        return count

    def test_rule_selection_statements_do_not_grow_with_orderpoints(self):
        self.rule_ids_statements(1)
        self.assertEqual(self.rule_ids_statements(3), self.rule_ids_statements(12))

    def qty_to_order_statements(self, count):
        count, quantities = self.statements(
            self.make_orderpoints(
                self.make_products(count, with_bom=True),
                route_id=self.manufacture_route.id,
            ),
            lambda orderpoints: orderpoints._get_qty_to_order_map(),
        )
        self.assertEqual(
            set(quantities.values()),
            {12.0},
            "10 units to order round up to the BoM's dozen",
        )
        return count

    def test_qty_to_order_statements_do_not_grow_with_orderpoints(self):
        self.qty_to_order_statements(1)
        self.assertEqual(
            self.qty_to_order_statements(3), self.qty_to_order_statements(12)
        )

    def lead_time_statements(self, count):
        count, _result = self.statements(
            self.make_orderpoints(
                self.make_products(count, with_bom=False),
                route_id=self.manufacture_route.id,
            ),
            lambda orderpoints: orderpoints._compute_lead_time(),
        )
        return count

    def test_lead_time_statements_do_not_grow_without_boms(self):
        self.lead_time_statements(1)
        self.assertEqual(self.lead_time_statements(3), self.lead_time_statements(12))

    def placeholder_statements(self, count):
        count, placeholders = self.statements(
            self.make_orderpoints(
                self.make_products(count, with_bom=True),
                route_id=self.manufacture_route.id,
            ),
            lambda orderpoints: orderpoints.mapped("bom_id_placeholder"),
        )
        self.assertTrue(all(placeholders))
        return count

    def test_placeholder_statements_do_not_grow_with_orderpoints(self):
        self.placeholder_statements(1)
        self.assertEqual(
            self.placeholder_statements(3), self.placeholder_statements(12)
        )

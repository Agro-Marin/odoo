from odoo import Command
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestOrderpointRuleKey(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env["stock.warehouse"].create(
            {"name": "Rule Key Warehouse", "code": "RKW"}
        )
        cls.stock = cls.warehouse.lot_stock_id
        cls.shelf = cls.env["stock.location"].create(
            {"name": "Key Shelf", "location_id": cls.warehouse.view_location_id.id}
        )
        cls.gated_route = cls.env["stock.route"].create(
            {
                "name": "Gated shelf route",
                "sequence": 1,
                "warehouse_selectable": True,
                "product_selectable": False,
                "warehouse_ids": [Command.link(cls.warehouse.id)],
            }
        )
        cls.gated_rule = cls.env["stock.rule"].create(
            {
                "name": "Shelf → Stock",
                "route_id": cls.gated_route.id,
                "action": "pull",
                "location_src_id": cls.shelf.id,
                "location_dest_id": cls.stock.id,
                "picking_type_id": cls.warehouse.int_type_id.id,
                "procure_method": "make_to_stock",
            }
        )
        cls.category = cls.env["product.category"].create({"name": "Rule Key"})
        cls.unusable = set()

    def setUp(self):
        super().setUp()
        Rule = type(self.env["stock.rule"])
        original = Rule._is_route_usable_for
        gated_route = self.gated_route
        unusable = self.unusable

        def is_route_usable_for(rule, product, route):
            if route == gated_route and product.id in unusable:
                return False
            return original(rule, product, route)

        self.patch(Rule, "_is_route_usable_for", is_route_usable_for)
        self.addCleanup(unusable.clear)

    def make_products(self, count, usable):
        products = self.env["product.product"].create(
            [
                {
                    "name": "Key %s %s" % ("usable" if usable else "gated", index),
                    "is_storable": True,
                    "categ_id": self.category.id,
                }
                for index in range(count)
            ]
        )
        if not usable:
            self.unusable.update(products.ids)
        return products

    def make_orderpoints(self, products):
        return self.env["stock.warehouse.orderpoint"].create(
            [
                {
                    "product_id": product.id,
                    "location_id": self.stock.id,
                    "warehouse_id": self.warehouse.id,
                }
                for product in products
            ]
        )

    def test_products_differing_only_by_route_usability_get_their_own_rules(self):
        usable = self.make_products(1, usable=True)
        gated = self.make_products(1, usable=False)
        alone = {
            product: product._get_rules_from_location(self.stock)
            for product in usable | gated
        }
        self.assertIn(self.gated_rule, alone[usable])
        self.assertNotIn(self.gated_rule, alone[gated])

        orderpoints = self.make_orderpoints(usable | gated)
        self.env.invalidate_all()
        for orderpoint in orderpoints.browse(orderpoints.ids):
            with self.subTest(product=orderpoint.product_id.name):
                self.assertEqual(orderpoint.rule_ids, alone[orderpoint.product_id])

    def rule_ids_statements(self, pairs):
        orderpoints = self.make_orderpoints(
            self.make_products(pairs, usable=True)
            | self.make_products(pairs, usable=False)
        )
        self.env.flush_all()
        self.env.invalidate_all()
        orderpoints = orderpoints.browse(orderpoints.ids)
        before = self.env.cr.sql_statement_count
        rules = orderpoints.mapped("rule_ids")
        statements = self.env.cr.sql_statement_count - before
        self.assertIn(self.gated_rule, rules)
        return statements

    def test_rule_selection_statements_do_not_grow_with_orderpoints(self):
        self.rule_ids_statements(1)
        self.assertEqual(self.rule_ids_statements(3), self.rule_ids_statements(12))

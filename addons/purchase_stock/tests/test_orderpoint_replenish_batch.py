from odoo import Command
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestOrderpointReplenishBatch(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.env.company.id)], limit=1
        )
        cls.buy_route = cls.warehouse.buy_pull_id.route_id
        cls.vendor = cls.env["res.partner"].create({"name": "Batch Vendor"})
        cls.pack = cls.env["uom.uom"].create(
            {
                "name": "Batch pack of 6",
                "relative_factor": 6.0,
                "relative_uom_id": cls.env.ref("uom.product_uom_unit").id,
            }
        )

    def make_orderpoints(self, count):
        products = self.env["product.product"].create(
            [
                {
                    "name": "Batch bought %s" % index,
                    "is_storable": True,
                    "route_ids": [Command.link(self.buy_route.id)],
                    "seller_ids": [
                        Command.create(
                            {
                                "partner_id": self.vendor.id,
                                "price": 3.0,
                                "product_uom_id": self.pack.id,
                            }
                        )
                    ],
                }
                for index in range(count)
            ]
        )
        return self.env["stock.warehouse.orderpoint"].create(
            [
                {
                    "product_id": product.id,
                    "location_id": self.warehouse.lot_stock_id.id,
                    "product_min_qty": 5.0,
                    "product_max_qty": 10.0,
                }
                for product in products
            ]
        )

    def qty_to_order_statements(self, count):
        orderpoints = self.make_orderpoints(count)
        self.env.flush_all()
        self.env.invalidate_all()
        orderpoints = orderpoints.browse(orderpoints.ids)
        before = self.env.cr.sql_statement_count
        quantities = orderpoints._get_qty_to_order_map()
        statements = self.env.cr.sql_statement_count - before
        self.assertEqual(
            set(quantities.values()),
            {12.0},
            "10 units to order round up to two packs of the vendor's 6",
        )
        return statements

    def test_qty_to_order_statements_do_not_grow_with_orderpoints(self):
        self.qty_to_order_statements(1)
        self.assertEqual(
            self.qty_to_order_statements(3), self.qty_to_order_statements(12)
        )

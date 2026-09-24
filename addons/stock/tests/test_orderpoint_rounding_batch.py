from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestOrderpointRoundingBatch(TransactionCase):
    def test_the_replenishment_multiple_is_resolved_once_per_batch(self):
        unit = self.env.ref("uom.product_uom_unit")
        pack = self.env["uom.uom"].create(
            {
                "name": "Batch pack of 4",
                "relative_factor": 4.0,
                "relative_uom_id": unit.id,
            }
        )
        products = self.env["product.product"].create(
            [{"name": "Rounded %s" % index, "is_storable": True} for index in range(3)]
        )
        stock = self.env.ref("stock.warehouse0").lot_stock_id
        Orderpoint = self.env["stock.warehouse.orderpoint"]
        orderpoints = Orderpoint.create(
            [
                {
                    "product_id": product.id,
                    "location_id": stock.id,
                    "product_min_qty": 5.0,
                    "product_max_qty": 10.0,
                }
                for product in products
            ]
        )
        pinned = orderpoints[0]
        pinned.replenishment_uom_id = pack
        calls = []

        def alternatives(records, qty_by_orderpoint):
            calls.append(records)
            return dict.fromkeys(records.ids, pack)

        self.patch(
            type(Orderpoint),
            "_get_replenishment_multiple_alternative_map",
            alternatives,
        )
        quantities = orderpoints._get_qty_to_order_map()

        self.assertEqual(len(calls), 1, "one alternative lookup per orderpoint")
        self.assertEqual(calls[0], orderpoints - pinned)
        self.assertEqual(set(quantities.values()), {12.0})

        calls.clear()
        forced = orderpoints._get_multiple_rounded_qty_map(
            dict.fromkeys(orderpoints.ids, 1.0)
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(set(forced.values()), {4.0})

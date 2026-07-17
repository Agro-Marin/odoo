from freezegun import freeze_time

from odoo import Command, fields
from odoo.tests import Form

from odoo.addons.stock.tests.common import TestStockCommon


class TestStockReplenish(TestStockCommon):
    def test_base_delay(self):
        """Open the replenish view and check if delay is taken into account
        in the base date computation
        """
        push_location = self.env["stock.location"].create(
            {
                "location_id": self.stock_location.location_id.id,
                "name": "push location",
            }
        )

        route_no_delay = self.env["stock.route"].create(
            {
                "name": "new route",
                "rule_ids": [
                    Command.create(
                        {
                            "name": "create a move to push location",
                            "location_src_id": self.stock_location.id,
                            "location_dest_id": push_location.id,
                            "company_id": self.env.company.id,
                            "action": "push",
                            "auto": "manual",
                            "picking_type_id": self.picking_type_in.id,
                            "delay": 0,
                        }
                    )
                ],
            }
        )

        route_delay = self.env["stock.route"].create(
            {
                "name": "new route",
                "rule_ids": [
                    Command.create(
                        {
                            "name": "create a move to push location",
                            "location_src_id": self.stock_location.id,
                            "location_dest_id": push_location.id,
                            "company_id": self.env.company.id,
                            "action": "push",
                            "auto": "manual",
                            "picking_type_id": self.picking_type_in.id,
                            "delay": 2,
                        }
                    ),
                    (
                        0,
                        False,
                        {
                            "name": "create a move to push location",
                            "location_src_id": push_location.id,
                            "location_dest_id": self.stock_location.id,
                            "company_id": self.env.company.id,
                            "action": "push",
                            "auto": "manual",
                            "picking_type_id": self.picking_type_in.id,
                            "delay": 4,
                        },
                    ),
                ],
            }
        )

        with freeze_time("2023-01-01"):
            wizard = Form(self.env["product.replenish"])
            wizard.route_id = route_no_delay
            self.assertEqual(
                fields.Datetime.from_string("2023-01-01 00:00:00"),
                wizard._values["date_planned"],
            )
            wizard.route_id = route_delay
            self.assertEqual(
                fields.Datetime.from_string("2023-01-07 00:00:00"),
                wizard._values["date_planned"],
            )

    def test_replenish_no_routes(self):
        product = self.env["product.template"].create(
            {
                "name": "Brand new product",
                "is_storable": True,
            }
        )
        self.assertEqual(len(product.route_ids), 0)
        wizard = Form(
            self.env["product.replenish"].with_context(
                default_product_tmpl_id=product.id
            )
        )
        self.assertEqual(wizard._values["quantity"], 1)

    def test_replenish_notifies_the_replenished_product(self):
        """``_get_record_to_notify`` must return the move created for *this*
        product. ``cr.now()`` is the transaction timestamp, so every move
        written in the transaction matches ``write_date >= now``; without a
        product filter the arbitrary (lowest-id) match could be an unrelated
        move, notifying the wrong document.
        """
        warehouse = self.warehouse_1
        route = self.env["stock.route"].create(
            {
                "name": "unit-replenish-route",
                "product_selectable": True,
                "rule_ids": [
                    Command.create(
                        {
                            "name": "receive",
                            "action": "pull",
                            "auto": "manual",
                            "location_src_id": self.supplier_location.id,
                            "location_dest_id": warehouse.lot_stock_id.id,
                            "picking_type_id": self.picking_type_in.id,
                            "procure_method": "make_to_stock",
                            "company_id": warehouse.company_id.id,
                        }
                    )
                ],
            }
        )
        product_a, product_b = self.env["product.product"].create(
            [
                {
                    "name": "Repl-A",
                    "is_storable": True,
                    "route_ids": [Command.set(route.ids)],
                },
                {
                    "name": "Repl-B",
                    "is_storable": True,
                    "route_ids": [Command.set(route.ids)],
                },
            ]
        )

        wizard = self.env["product.replenish"].create(
            {
                "product_id": product_a.id,
                "product_tmpl_id": product_a.product_tmpl_id.id,
                "product_uom_id": product_a.uom_id.id,
                "quantity": 7,
                "warehouse_id": warehouse.id,
                "route_id": route.id,
                "date_planned": self.env.cr.now(),
            }
        )

        # An unrelated move for product B, present in the same transaction with a
        # lower id than the move the wizard is about to create.
        self.env["stock.move"].create(
            {
                "product_id": product_b.id,
                "product_uom_qty": 99,
                "company_id": warehouse.company_id.id,
                "date": self.env.cr.now(),
                "procure_method": "make_to_stock",
                "location_id": self.supplier_location.id,
                "location_dest_id": warehouse.lot_stock_id.id,
            }
        )
        self.env.flush_all()

        now = self.env.cr.now()
        wizard.launch_replenishment()
        notified = wizard._get_record_to_notify(now)

        self.assertTrue(notified, "a move should have been created and notified")
        self.assertEqual(
            notified.product_id,
            product_a,
            "the notification must point at the replenished product, not an "
            "unrelated move sharing the transaction timestamp",
        )
        self.assertEqual(notified.product_uom_qty, 7)

    def _weight_orderpoint(self):
        return self.env["stock.warehouse.orderpoint"].create(
            {
                "product_id": self.kgB.id,
                "location_id": self.stock_location.id,
                "warehouse_id": self.warehouse_1.id,
            },
        )

    def test_get_multiple_rounded_qty_skips_cross_category_multiple(self):
        """A replenishment multiple UoM left cross-category by legacy data (a
        Weight product carrying a Units multiple) must be skipped, not raise.
        Before the fix `_get_multiple_rounded_qty` called `uom._compute_quantity`
        with `raise_if_failure=True` and blocked POS checkout via the orderpoint
        recompute triggered when confirming an order with lot selection.
        """
        orderpoint = self._weight_orderpoint()
        orderpoint.replenishment_uom_id = self.uom_unit
        self.assertFalse(self.uom_kg._has_common_reference(self.uom_unit))

        # Multiple is inapplicable across categories: the qty is returned
        # unrounded (still correct in the product UoM) instead of raising.
        self.assertEqual(orderpoint._get_multiple_rounded_qty(4.3), 4.3)

    def test_get_multiple_rounded_qty_rounds_when_compatible(self):
        """A same-reference multiple must still round the order up so it fully
        covers the shortage — the guard only skips cross-category multiples.
        """
        orderpoint = self._weight_orderpoint()
        orderpoint.replenishment_uom_id = self.uom_kg

        self.assertEqual(orderpoint._get_multiple_rounded_qty(4.3), 5.0)

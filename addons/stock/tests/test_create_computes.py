from odoo import Command
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCreateComputes(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product = cls.env["product.product"].create(
            {"name": "Create computes", "is_storable": True}
        )
        cls.stock = cls.env.ref("stock.stock_location_stock")
        cls.customers = cls.env.ref("stock.stock_location_customers")

    def _move_vals(self, **extra):
        return {
            "product_id": self.product.id,
            "product_uom_qty": 1.0,
            "location_id": self.stock.id,
            "location_dest_id": self.customers.id,
            **extra,
        }

    def _line_vals(self, **extra):
        return {
            "product_id": self.product.id,
            "quantity": 1.0,
            "location_id": self.stock.id,
            "location_dest_id": self.customers.id,
            **extra,
        }

    def test_a_move_created_with_picked_lines_keeps_them_picked(self):
        move = self.env["stock.move"].create(
            self._move_vals(
                move_line_ids=[Command.create(self._line_vals(picked=True))]
            )
        )

        self.assertTrue(move.move_line_ids.picked)
        self.assertTrue(move.picked)

    def test_a_move_created_with_unpicked_lines_is_not_picked(self):
        move = self.env["stock.move"].create(
            self._move_vals(move_line_ids=[Command.create(self._line_vals())])
        )

        self.assertFalse(move.move_line_ids.picked)
        self.assertFalse(move.picked)

    def test_a_move_created_without_lines_is_not_picked(self):
        move = self.env["stock.move"].create(self._move_vals())

        self.assertFalse(move.picked)

    def test_an_explicit_picked_reaches_the_lines(self):
        move = self.env["stock.move"].create(
            self._move_vals(
                picked=True, move_line_ids=[Command.create(self._line_vals())]
            )
        )

        self.assertTrue(move.move_line_ids.picked)

    def test_an_orderpoint_with_only_a_minimum_replenishes_up_to_it(self):
        orderpoint = self.env["stock.warehouse.orderpoint"].create(
            {"product_id": self.product.id, "product_min_qty": 5.0}
        )

        self.assertEqual(orderpoint.product_max_qty, 5.0)

    def test_an_explicit_orderpoint_maximum_wins(self):
        orderpoint = self.env["stock.warehouse.orderpoint"].create(
            {
                "product_id": self.product.id,
                "product_min_qty": 5.0,
                "product_max_qty": 8.0,
            }
        )

        self.assertEqual(orderpoint.product_max_qty, 8.0)

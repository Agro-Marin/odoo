"""Tests for valuation-line eligibility and the equal-split distribution."""

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestLandedCostSplit(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.cost_product = cls.env["product.product"].create(
            {"name": "LC split cost", "type": "service", "landed_cost_ok": True}
        )
        cls.fifo_category = cls.env["product.category"].create(
            {
                "name": "LC FIFO categ",
                "property_cost_method": "fifo",
                "property_valuation": "periodic",
            }
        )
        cls.std_category = cls.env["product.category"].create(
            {
                "name": "LC STD categ",
                "property_cost_method": "standard",
                "property_valuation": "periodic",
            }
        )
        cls.stock_location = cls.env.ref("stock.stock_location_stock")
        cls.supplier_location = cls.env.ref("stock.stock_location_suppliers")

    def _picking_with_move(self, product, quantity):
        picking = self.env["stock.picking"].create(
            {
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
                "picking_type_id": self.env.ref("stock.picking_type_in").id,
            }
        )
        self.env["stock.move"].create(
            {
                "product_id": product.id,
                "product_uom_id": product.uom_id.id,
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
                "picking_id": picking.id,
                "quantity": quantity,
                "state": "done",
            }
        )
        return picking

    def _product(self, name, category):
        return self.env["product.product"].create(
            {
                "name": name,
                "type": "consu",
                "is_storable": True,
                "categ_id": category.id,
            }
        )

    def test_valuation_lines_standard_cost_rejected(self):
        """Landed costs only apply to FIFO/average products (negative)."""
        product = self._product("LC std product", self.std_category)
        cost = self.env["stock.landed.cost"].create(
            {
                "picking_ids": [Command.set(self._picking_with_move(product, 2.0).ids)],
                "cost_lines": [
                    Command.create(
                        {
                            "product_id": self.cost_product.id,
                            "price_unit": 100.0,
                            "split_method": "equal",
                        }
                    )
                ],
            }
        )
        with self.assertRaises(UserError):
            cost.get_valuation_lines()

    def test_compute_landed_cost_split_equal(self):
        """An equal split spreads the cost line evenly across moves."""
        product_a = self._product("LC fifo A", self.fifo_category)
        product_b = self._product("LC fifo B", self.fifo_category)
        picking = self._picking_with_move(product_a, 2.0)
        picking_b = self._picking_with_move(product_b, 6.0)
        cost = self.env["stock.landed.cost"].create(
            {
                "picking_ids": [Command.set((picking | picking_b).ids)],
                "cost_lines": [
                    Command.create(
                        {
                            "product_id": self.cost_product.id,
                            "price_unit": 100.0,
                            "split_method": "equal",
                        }
                    )
                ],
            }
        )
        cost.compute_landed_cost()
        adjustments = cost.valuation_adjustment_lines
        self.assertEqual(len(adjustments), 2)
        self.assertEqual(adjustments.mapped("additional_landed_cost"), [50.0, 50.0])

    def test_validate_periodic_products_posts_no_entry(self):
        """Validation completes without a journal entry for periodic products."""
        product = self._product("LC fifo E", self.fifo_category)
        cost = self.env["stock.landed.cost"].create(
            {
                "picking_ids": [Command.set(self._picking_with_move(product, 2.0).ids)],
                "cost_lines": [
                    Command.create(
                        {
                            "product_id": self.cost_product.id,
                            "price_unit": 100.0,
                            "split_method": "equal",
                        }
                    )
                ],
            }
        )
        cost.button_validate()
        self.assertEqual(cost.state, "done")
        self.assertFalse(cost.account_move_id)

    def test_compute_landed_cost_split_by_quantity(self):
        """A by-quantity split weighs each move by its received quantity."""
        product_a = self._product("LC fifo C", self.fifo_category)
        product_b = self._product("LC fifo D", self.fifo_category)
        cost = self.env["stock.landed.cost"].create(
            {
                "picking_ids": [
                    Command.set(
                        (
                            self._picking_with_move(product_a, 2.0)
                            | self._picking_with_move(product_b, 6.0)
                        ).ids
                    )
                ],
                "cost_lines": [
                    Command.create(
                        {
                            "product_id": self.cost_product.id,
                            "price_unit": 80.0,
                            "split_method": "by_quantity",
                        }
                    )
                ],
            }
        )
        cost.compute_landed_cost()
        self.assertEqual(
            cost.valuation_adjustment_lines.mapped("additional_landed_cost"),
            [20.0, 60.0],
        )

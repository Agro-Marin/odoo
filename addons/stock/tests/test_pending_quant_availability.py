from odoo.tests import tagged

from odoo.addons.stock.tests.common import TestStockCommon


@tagged("post_install", "-at_install")
class TestPendingQuantAvailability(TestStockCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.MoveLine = cls.env["stock.move.line"]
        cls.uom_unit = cls.env.ref("uom.product_uom_unit")
        cls.uom_dozen = cls.env.ref("uom.product_uom_dozen")
        cls.picking_type_out = cls.env.ref("stock.picking_type_out")

    def _make_product(self, name="AVAIL-PROBE"):
        return self.env["product.product"].create(
            {
                "name": name,
                "is_storable": True,
                "type": "consu",
                "uom_id": self.uom_unit.id,
            }
        )

    def _make_move(self, product, qty, uom, on_hand=None):
        if on_hand is not None:
            self.env["stock.quant"]._update_available_quantity(
                product, self.stock_location, on_hand
            )
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.picking_type_out.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
            }
        )
        move = self.env["stock.move"].create(
            {
                "product_id": product.id,
                "product_uom_qty": qty,
                "product_uom_id": uom.id,
                "picking_id": picking.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
            }
        )
        picking.action_confirm()
        picking.action_assign()
        return move

    def _pending(self, move, **overrides):
        return [
            {
                "id": ml.id,
                "quantity": overrides.get("quantity", ml.quantity),
                "quant_id": overrides.get("quant_id", False),
            }
            for ml in move.move_line_ids
        ]

    def _quant_of(self, product):
        return self.env["stock.quant"].search(
            [
                ("product_id", "=", product.id),
                ("location_id", "=", self.stock_location.id),
            ]
        )

    def test_result_is_expressed_in_the_move_uom(self):
        product = self._make_product()
        move = self._make_move(product, 1.0, self.uom_dozen, on_hand=24.0)
        self.assertEqual(move.move_line_ids.product_uom_id, self.uom_dozen)
        self.assertEqual(move.move_line_ids.quantity, 1.0)
        self.assertEqual(move.move_line_ids.quantity_product_uom, 12.0)

        availability = self.MoveLine.get_pending_quant_availability(
            move.id, self._pending(move, quantity=0.5)
        )

        self.assertEqual(len(availability), 1)
        quant_id, available = availability[0]
        self.assertEqual(quant_id, self._quant_of(product).id)
        self.assertEqual(
            available, 1.5, "18 free Units is 1.5 Dozens, not 18 and not 0.5"
        )

    def test_same_uom_is_unaffected(self):
        product = self._make_product()
        move = self._make_move(product, 12.0, self.uom_unit, on_hand=24.0)

        availability = self.MoveLine.get_pending_quant_availability(
            move.id, self._pending(move, quantity=6.0)
        )

        self.assertEqual(availability, [[self._quant_of(product).id, 18.0]])

    def test_deleting_every_line_releases_the_whole_reservation(self):
        product = self._make_product()
        move = self._make_move(product, 1.0, self.uom_dozen, on_hand=24.0)

        availability = self.MoveLine.get_pending_quant_availability(move.id, [])

        self.assertEqual(availability, [[self._quant_of(product).id, 2.0]])

    def test_a_new_line_consumes_in_the_move_uom(self):
        product = self._make_product()
        move = self._make_move(product, 1.0, self.uom_dozen, on_hand=24.0)
        quant = self._quant_of(product)
        pending = self._pending(move)
        pending.append({"id": False, "quantity": 0.5, "quant_id": quant.id})

        availability = self.MoveLine.get_pending_quant_availability(move.id, pending)

        self.assertEqual(availability, [[quant.id, 0.5]])

    def test_an_unchanged_form_asks_about_nothing(self):
        product = self._make_product()
        move = self._make_move(product, 1.0, self.uom_dozen, on_hand=24.0)

        self.assertEqual(
            self.MoveLine.get_pending_quant_availability(move.id, self._pending(move)),
            [],
        )

    def test_repicking_the_same_quant_returns_the_saved_reservation(self):
        product = self._make_product()
        move = self._make_move(product, 12.0, self.uom_unit, on_hand=24.0)
        quant = self._quant_of(product)

        availability = self.MoveLine.get_pending_quant_availability(
            move.id,
            [
                {"id": ml.id, "quantity": 4.0, "quant_id": quant.id}
                for ml in move.move_line_ids
            ],
        )

        self.assertEqual(availability, [[quant.id, 20.0]])

    def test_a_missing_move_is_not_an_error(self):
        self.assertEqual(self.MoveLine.get_pending_quant_availability(0, []), [])

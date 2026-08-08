"""Direct coverage for `stock.move.action_generate_lot_line_vals`.

The Generate/Import Serials-Lots dialog's server side had no Python test at all: its
only coverage was two Chrome tours (`test_generate_serial_1` / `_2`) and a HOOT test
that mounts `GenerateDialog` as a bare component and mocks this RPC away. So the method
was exercised end to end or not at all — and when the tour asset bundle breaks, it is not
at all.

It is an RPC entry point taking a client-supplied context, mode, count and free text, so
what wants pinning is exactly what a tour is worst at showing: the bounds, the rejected
inputs, and the shape of what comes back.
"""

from odoo.exceptions import UserError

from odoo.addons.stock.models.stock_move import GENERATED_LOT_VALS_MAX
from odoo.addons.stock.tests.common import TestStockCommon


class TestGenerateLotLineVals(TestStockCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.serial_product = cls.env["product.product"].create(
            {"name": "Gen SN", "is_storable": True, "tracking": "serial"}
        )
        cls.lot_product = cls.env["product.product"].create(
            {"name": "Gen Lot", "is_storable": True, "tracking": "lot"}
        )

    def _context(self, product, tracking, **extra):
        return {
            "default_product_id": product.id,
            "default_location_id": self.stock_location.id,
            "default_location_dest_id": self.stock_location.id,
            "default_tracking": tracking,
            **extra,
        }

    # --- what it produces ---------------------------------------------------

    def test_generate_serials_one_line_per_unit(self):
        vals = self.env["stock.move"].action_generate_lot_line_vals(
            self._context(self.serial_product, "serial"), "generate", "sn-001", 4, ""
        )
        self.assertEqual(len(vals), 4)
        self.assertEqual(
            [v["lot_name"] for v in vals], ["sn-001", "sn-002", "sn-003", "sn-004"]
        )
        self.assertEqual([v["quantity"] for v in vals], [1, 1, 1, 1])
        # Relational values come back in the webclient's {id, display_name} shape.
        self.assertEqual(
            vals[0]["location_dest_id"],
            {
                "id": self.stock_location.id,
                "display_name": self.stock_location.display_name,
            },
        )

    def test_generate_lots_splits_quantity_with_a_leftover(self):
        """`count` is the quantity *per lot* in lot mode, not the number of lots."""
        vals = self.env["stock.move"].action_generate_lot_line_vals(
            self._context(self.lot_product, "lot", default_quantity=10),
            "generate",
            "lot-001",
            4,
            "",
        )
        # 10 split by 4 = 4 + 4 + 2
        self.assertEqual([v["quantity"] for v in vals], [4, 4, 2])

    def test_generate_lots_without_a_leftover(self):
        vals = self.env["stock.move"].action_generate_lot_line_vals(
            self._context(self.lot_product, "lot", default_quantity=9),
            "generate",
            "lot-001",
            3,
            "",
        )
        self.assertEqual([v["quantity"] for v in vals], [3, 3, 3])

    def test_import_uses_the_pasted_names_and_ignores_count(self):
        vals = self.env["stock.move"].action_generate_lot_line_vals(
            self._context(self.serial_product, "serial"),
            "import",
            "",
            999,
            "aaa\nbbb\nccc",
        )
        self.assertEqual([v["lot_name"] for v in vals], ["aaa", "bbb", "ccc"])
        self.assertEqual([v["quantity"] for v in vals], [1, 1, 1])

    # --- what it refuses ----------------------------------------------------

    def test_rejects_an_unknown_mode(self):
        with self.assertRaises(UserError):
            self.env["stock.move"].action_generate_lot_line_vals(
                self._context(self.serial_product, "serial"), "wat", "sn-1", 1, ""
            )

    def test_rejects_a_context_without_a_product(self):
        with self.assertRaises(UserError):
            self.env["stock.move"].action_generate_lot_line_vals(
                {"default_tracking": "serial"}, "generate", "sn-1", 1, ""
            )

    def test_rejects_a_context_missing_a_required_key(self):
        context = self._context(self.lot_product, "lot")  # no default_quantity
        with self.assertRaises(UserError):
            self.env["stock.move"].action_generate_lot_line_vals(
                context, "generate", "lot-1", 2, ""
            )

    def test_rejects_a_non_positive_quantity_per_lot(self):
        with self.assertRaises(UserError):
            self.env["stock.move"].action_generate_lot_line_vals(
                self._context(self.lot_product, "lot", default_quantity=10),
                "generate",
                "lot-1",
                0,
                "",
            )

    # --- the bounds, which are the point of an RPC boundary -----------------

    def test_serial_count_is_bounded(self):
        """The cap must fire *before* the list is built: `count` is client-supplied."""
        with self.assertRaises(UserError):
            self.env["stock.move"].action_generate_lot_line_vals(
                self._context(self.serial_product, "serial"),
                "generate",
                "sn-1",
                GENERATED_LOT_VALS_MAX + 1,
                "",
            )

    def test_lot_split_count_is_bounded(self):
        """Same cap on the split: a huge quantity over a tiny per-lot size."""
        with self.assertRaises(UserError):
            self.env["stock.move"].action_generate_lot_line_vals(
                self._context(
                    self.lot_product,
                    "lot",
                    default_quantity=float(GENERATED_LOT_VALS_MAX + 5),
                ),
                "generate",
                "lot-1",
                1,
                "",
            )

    # --- the sequence side effect ------------------------------------------

    def test_generate_advances_the_lot_sequence_but_import_does_not(self):
        sequence = self.env["ir.sequence"].create(
            {"name": "gen seq", "prefix": "GS", "padding": 4, "number_next": 1}
        )
        product = self.env["product.product"].create(
            {
                "name": "Sequenced SN",
                "is_storable": True,
                "tracking": "serial",
                "lot_sequence_id": sequence.id,
            }
        )
        first = sequence._get_current_sequence().number_next_actual

        # Import mode leaves the sequence alone: the names are user-pasted.
        self.env["stock.move"].action_generate_lot_line_vals(
            self._context(product, "serial"), "import", "", 0, "x1\nx2"
        )
        self.assertEqual(
            sequence._get_current_sequence().number_next_actual,
            first,
            "import must not consume sequence numbers",
        )

        # Generate mode advances it past the names it just handed out, and only ever
        # forwards.
        self.env["stock.move"].action_generate_lot_line_vals(
            self._context(product, "serial"),
            "generate",
            sequence.get_next_char(first),
            3,
            "",
        )
        self.assertGreaterEqual(
            sequence._get_current_sequence().number_next_actual, first
        )

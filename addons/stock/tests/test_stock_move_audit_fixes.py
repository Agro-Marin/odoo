from unittest.mock import patch

import psycopg

from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestStockMoveAuditFixes(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.wh = cls.env["stock.warehouse"].search([], limit=1)
        cls.stock_loc = cls.wh.lot_stock_id
        cls.supplier = cls.env.ref("stock.stock_location_suppliers")
        cls.customer = cls.env.ref("stock.stock_location_customers")
        cls.Move = cls.env["stock.move"]
        cls.Picking = cls.env["stock.picking"]

    def _product(self, name, **kw):
        return self.env["product.product"].create(
            {"name": name, "is_storable": True, **kw},
        )

    def test_refused_unlink_leaves_the_reservation_intact(self):
        product = self._product("A1")
        self.env["stock.quant"]._update_available_quantity(
            product,
            self.stock_loc,
            100,
        )
        upstream = self.Move.create(
            {
                "product_id": product.id,
                "product_uom_qty": 5,
                "location_id": self.stock_loc.id,
                "location_dest_id": self.wh.wh_output_stock_loc_id.id,
                "picking_type_id": self.wh.int_type_id.id,
            },
        )
        downstream = self.Move.create(
            {
                "product_id": product.id,
                "product_uom_qty": 5,
                "location_id": self.wh.wh_output_stock_loc_id.id,
                "location_dest_id": self.customer.id,
                "picking_type_id": self.wh.out_type_id.id,
                "procure_method": "make_to_order",
                "move_orig_ids": [Command.set(upstream.ids)],
            },
        )
        (upstream | downstream)._action_confirm(merge=False)
        upstream._action_assign()
        self.assertEqual(upstream.state, "assigned")
        lines_before = upstream.move_line_ids
        self.assertTrue(lines_before)

        line_ids_before = lines_before.ids
        self.env.flush_all()

        refused = None
        try:
            upstream.unlink()
        except UserError as exc:
            refused = exc
        self.assertIsNotNone(refused, "the ondelete guard must refuse this delete")

        self.env.cr.execute(
            "SELECT count(*) FROM stock_move_line WHERE id = ANY(%s)",
            (line_ids_before,),
        )
        surviving = self.env.cr.fetchone()[0]
        self.env.invalidate_all()
        self.assertTrue(upstream.exists(), "the guard refused, so the move stays")
        self.assertEqual(
            surviving,
            len(line_ids_before),
            "a refused unlink deleted the move's reservation lines anyway: "
            "unlink() destroys before its @api.ondelete guard validates",
        )
        self.assertEqual(upstream.state, "assigned")

    def test_generate_lot_line_vals_rejects_a_non_numeric_count(self):
        product = self._product("A2", tracking="serial")
        context_data = {
            "default_product_id": product.id,
            "default_tracking": "serial",
            "default_location_dest_id": self.stock_loc.id,
            "default_picking_type_id": self.wh.in_type_id.id,
        }
        for bad_count in ("abc", 2.5, None, [3]):
            with self.subTest(count=bad_count), self.assertRaises(UserError):
                self.Move.action_generate_lot_line_vals(
                    context_data,
                    "generate",
                    "SN0001",
                    bad_count,
                    "",
                )
        self.assertEqual(
            len(
                self.Move.action_generate_lot_line_vals(
                    context_data,
                    "generate",
                    "SN0001",
                    "3",
                    "",
                ),
            ),
            3,
        )

    def test_generate_lot_line_vals_rejects_a_non_string_lot_text(self):
        product = self._product("A2b", tracking="serial")
        context_data = {
            "default_product_id": product.id,
            "default_tracking": "serial",
            "default_location_dest_id": self.stock_loc.id,
            "default_picking_type_id": self.wh.in_type_id.id,
        }
        with self.assertRaises(UserError):
            self.Move.action_generate_lot_line_vals(
                context_data,
                "import",
                "",
                0,
                12345,
            )

    def test_move_added_to_a_done_picking_resolves_its_source(self):
        product = self._product("A9")
        picking = self.Picking.create(
            {
                "picking_type_id": self.wh.in_type_id.id,
                "location_id": self.supplier.id,
                "location_dest_id": self.stock_loc.id,
                "move_ids": [
                    Command.create(
                        {
                            "product_id": product.id,
                            "product_uom_qty": 3,
                            "location_id": self.supplier.id,
                            "location_dest_id": self.stock_loc.id,
                        },
                    ),
                ],
            },
        )
        picking.action_confirm()
        picking.move_ids.picked = True
        picking.button_validate()
        self.assertEqual(picking.state, "done")

        extra_product = self._product("A9-extra")
        try:
            extra = self.Move.create(
                {
                    "product_id": extra_product.id,
                    "product_uom_qty": 2,
                    "picking_id": picking.id,
                    "location_dest_id": self.stock_loc.id,
                },
            )
            self.env.flush_all()
        except psycopg.errors.NotNullViolation:
            self.fail(
                "creating a move on a done picking raised a raw NotNullViolation: "
                "_compute_location_id skipped the picked move and left the "
                "required source location unset",
            )
        self.assertEqual(extra.location_id, picking.location_id)

    def _negative_move_with_a_chain(self, upstream_dest):
        product = self._product(f"A6-{upstream_dest.name}")
        self.env["stock.quant"]._update_available_quantity(
            product,
            self.stock_loc,
            50,
        )
        sub = self.env["stock.location"].create(
            {
                "name": f"A6-SUB-{upstream_dest.name}",
                "usage": "internal",
                "location_id": self.stock_loc.id,
            },
        )
        upstream = self.Move.create(
            {
                "product_id": product.id,
                "product_uom_qty": 5,
                "location_id": self.stock_loc.id,
                "location_dest_id": upstream_dest.id,
                "picking_type_id": self.wh.int_type_id.id,
            },
        )
        upstream._action_confirm(merge=False)
        negative = self.Move.create(
            {
                "product_id": product.id,
                "product_uom_qty": -3,
                "location_id": self.stock_loc.id,
                "location_dest_id": sub.id,
                "picking_type_id": self.wh.int_type_id.id,
                "move_orig_ids": [Command.set(upstream.ids)],
            },
        )
        self.env["stock.move.line"].create(
            {
                "move_id": negative.id,
                "product_id": product.id,
                "product_uom_id": product.uom_id.id,
                "quantity": 2.0,
                "location_id": self.stock_loc.id,
                "location_dest_id": sub.id,
            },
        )
        self.env.flush_all()
        return upstream, negative, sub

    def test_reversing_a_negative_move_keeps_its_chain(self):
        upstream, negative, _sub = self._negative_move_with_a_chain(self.stock_loc)
        negative._action_confirm(merge=False)

        self.assertTrue(negative.exists())
        self.assertIn(
            upstream,
            negative.move_orig_ids | negative.move_dest_ids,
            "the reversal must rewire the chain link, not drop it",
        )

    def test_reversing_a_negative_move_keeps_an_upstream_as_an_origin(self):
        sub = self.env["stock.location"].create(
            {
                "name": "A6-ORIG-DEST",
                "usage": "internal",
                "location_id": self.stock_loc.id,
            },
        )
        product = self._product("A6-orig")
        self.env["stock.quant"]._update_available_quantity(
            product,
            self.stock_loc,
            50,
        )
        upstream = self.Move.create(
            {
                "product_id": product.id,
                "product_uom_qty": 5,
                "location_id": self.stock_loc.id,
                "location_dest_id": sub.id,
                "picking_type_id": self.wh.int_type_id.id,
            },
        )
        upstream._action_confirm(merge=False)
        negative = self.Move.create(
            {
                "product_id": product.id,
                "product_uom_qty": -3,
                "location_id": self.stock_loc.id,
                "location_dest_id": sub.id,
                "picking_type_id": self.wh.int_type_id.id,
                "move_orig_ids": [Command.set(upstream.ids)],
            },
        )
        self.env["stock.move.line"].create(
            {
                "move_id": negative.id,
                "product_id": product.id,
                "product_uom_id": product.uom_id.id,
                "quantity": 2.0,
                "location_id": self.stock_loc.id,
                "location_dest_id": sub.id,
            },
        )
        self.env.flush_all()
        negative._action_confirm(merge=False)

        self.assertTrue(negative.exists())
        self.assertEqual(negative.location_id, sub)
        self.assertEqual(
            negative.move_orig_ids,
            upstream,
            "a move delivering into the reversed source stays an origin",
        )

    def _chained_batch(self, size, prefix):
        out_loc = self.wh.wh_output_stock_loc_id or self.stock_loc
        products = self.env["product.product"].create(
            [
                {"name": f"{prefix}{i}", "is_storable": True, "type": "consu"}
                for i in range(size)
            ],
        )
        for product in products:
            self.env["stock.quant"]._update_available_quantity(
                product,
                self.stock_loc,
                500,
            )
        upstream = self.Move.create(
            [
                {
                    "product_id": product.id,
                    "product_uom_qty": 10,
                    "location_id": self.stock_loc.id,
                    "location_dest_id": out_loc.id,
                    "picking_type_id": self.wh.int_type_id.id,
                }
                for product in products
            ],
        )
        downstream = self.Move.create(
            [
                {
                    "product_id": product.id,
                    "product_uom_qty": 10,
                    "location_id": out_loc.id,
                    "location_dest_id": self.customer.id,
                    "picking_type_id": self.wh.out_type_id.id,
                    "procure_method": "make_to_order",
                    "move_orig_ids": [Command.set(up.ids)],
                }
                for product, up in zip(products, upstream, strict=True)
            ],
        )
        (upstream | downstream)._action_confirm(merge=False)
        upstream._action_assign()
        upstream.picked = True
        upstream._action_done()
        downstream._do_unreserve(force=True)
        downstream.write({"state": "confirmed"})
        self.env.flush_all()
        return downstream.ids

    def test_assigning_a_chained_batch_does_not_walk_the_origin_chain_per_move(self):
        move_ids = self._chained_batch(20, "PFC")
        Move = type(self.Move)
        original = Move._get_available_move_lines
        walked_queries = []

        def counting(records, *args, **kwargs):
            before = records.env.cr.sql_log_count
            try:
                return original(records, *args, **kwargs)
            finally:
                walked_queries.append(records.env.cr.sql_log_count - before)

        self.env.invalidate_all()
        moves = self.Move.browse(move_ids)
        with patch.object(Move, "_get_available_move_lines", counting):
            moves._action_assign()
        self.env.flush_all()

        self.assertEqual(
            set(moves.mapped("state")),
            {"assigned"},
            "the batch must end reserved",
        )
        self.assertEqual(len(walked_queries), 20, "every move walks its own chain")
        self.assertEqual(
            sum(walked_queries),
            0,
            f"{sum(walked_queries)} queries walking the origin chain: the batch "
            f"prefetch in `_prepare_reservation_run` is no longer covering it",
        )

    def test_split_lots_reads_one_format_for_the_whole_block(self):
        seen = []
        original = type(self.Move)._get_formatting_options

        def recording(records, strings):
            seen.append(list(strings))
            return original(records, strings)

        with patch.object(type(self.Move), "_get_formatting_options", recording):
            self.Move.split_lots("SN01\t12\nSN02\t7\nSN03\t3")

        self.assertEqual(
            len(seen),
            1,
            "the options are resolved once, not once per line",
        )
        self.assertEqual(
            seen[0],
            ["12", "7", "3"],
            "and from every line's extra parts, not just the first line's",
        )

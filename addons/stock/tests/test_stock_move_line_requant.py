from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestMoveLineRequant(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.stock = cls.env.ref("stock.stock_location_stock")
        cls.supplier = cls.env.ref("stock.stock_location_suppliers")
        cls.customer = cls.env.ref("stock.stock_location_customers")
        cls.inventory = cls.env["stock.location"].search(
            [("usage", "=", "inventory")], limit=1
        )
        cls.shelf_1 = cls.env["stock.location"].create(
            {"name": "R-Shelf1", "location_id": cls.stock.id, "usage": "internal"}
        )
        cls.shelf_2 = cls.env["stock.location"].create(
            {"name": "R-Shelf2", "location_id": cls.stock.id, "usage": "internal"}
        )
        cls.old_date = fields.Datetime.to_datetime("2020-01-01 00:00:00")

    def _product(self, name, **vals):
        return self.env["product.product"].create(
            {"name": name, "is_storable": True, **vals}
        )

    def _done_move(self, product, src, dst, qty, seed_source=False):
        if seed_source:
            self.env["stock.quant"]._update_available_quantity(
                product, src, qty, in_date=self.old_date
            )
        move = self.env["stock.move"].create(
            {
                "location_id": src.id,
                "location_dest_id": dst.id,
                "product_id": product.id,
                "product_uom_id": product.uom_id.id,
                "product_uom_qty": qty,
            }
        )
        move._action_confirm()
        move._action_assign()
        move.move_line_ids.quantity = qty
        move.picked = True
        move._action_done()
        return move

    def _dest_quant(self, product, location):
        return (
            self.env["stock.quant"]
            ._gather(product, location)
            .filtered(lambda quant: quant.quantity > 0)
        )

    def _backdate(self, product, location):
        quants = self.env["stock.quant"].search(
            [("product_id", "=", product.id), ("location_id", "=", location.id)]
        )
        quants.invalidate_recordset(["in_date"])
        self.env.cr.execute(
            "UPDATE stock_quant SET in_date = %s WHERE id = ANY(%s)",
            (self.old_date, list(quants.ids)),
        )
        self.env.invalidate_all()


    def test_editing_a_done_line_keeps_the_receipt_date(self):
        for label, src, seed in (
            ("internal", self.shelf_1, True),
            ("receipt", self.supplier, False),
            ("inventory", self.inventory, False),
        ):
            with self.subTest(source=label):
                product = self._product("KeepDate-%s" % label)
                move = self._done_move(
                    product, src, self.shelf_2, 10.0, seed_source=seed
                )
                if not seed:
                    self._backdate(product, self.shelf_2)
                self.assertEqual(
                    self._dest_quant(product, self.shelf_2).in_date, self.old_date
                )

                move.move_line_ids.quantity = 5.0

                quant = self._dest_quant(product, self.shelf_2)
                self.assertEqual(quant.quantity, 5.0)
                self.assertEqual(
                    quant.in_date,
                    self.old_date,
                    "correcting a done line must not restamp the receipt date",
                )

    def test_moving_a_done_line_keeps_the_destination_receipt_date(self):
        source_only = [
            ("source location", lambda self: {"location_id": self.shelf_1.id}),
            (
                "source package",
                lambda self: {
                    "package_id": self.env["stock.package"]
                    .create({"name": "KeepDestPack"})
                    .id
                },
            ),
        ]
        for label, make_vals in source_only:
            with self.subTest(changed=label):
                product = self._product("KeepDest-%s" % label.replace(" ", ""))
                move = self._done_move(
                    product, self.shelf_1, self.shelf_2, 10.0, seed_source=True
                )
                self._backdate(product, self.shelf_2)
                self.assertEqual(
                    self._dest_quant(product, self.shelf_2).in_date, self.old_date
                )

                move.move_line_ids.write(make_vals(self))

                quants = self.env["stock.quant"].search(
                    [
                        ("product_id", "=", product.id),
                        ("location_id", "=", self.shelf_2.id),
                        ("quantity", ">", 0),
                    ]
                )
                self.assertTrue(quants)
                self.assertEqual(
                    quants.mapped("in_date"),
                    [self.old_date] * len(quants),
                    "the destination did not move, so its receipt date must stand",
                )

    def test_a_write_that_changes_nothing_leaves_the_quant_alone(self):
        product = self._product("NoopWrite")
        move = self._done_move(product, self.supplier, self.stock, 5.0)
        self._backdate(product, self.stock)
        line = move.move_line_ids

        for vals in (
            {"quantity": 5.0},
            {"owner_id": False},
            {"result_package_id": False},
            {"location_dest_id": line.location_dest_id.id},
            {"product_uom_id": line.product_uom_id.id},
        ):
            with self.subTest(vals=vals):
                line.write(vals)
                self.assertEqual(
                    self._dest_quant(product, self.stock).in_date,
                    self.old_date,
                    "a write that changes no value must not move quants",
                )

    def test_a_no_op_write_posts_no_chatter(self):
        product = self._product("NoopChatter")
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.env.ref("stock.picking_type_in").id,
                "location_id": self.supplier.id,
                "location_dest_id": self.stock.id,
            }
        )
        self.env["stock.move"].create(
            {
                "product_id": product.id,
                "product_uom_id": product.uom_id.id,
                "product_uom_qty": 5.0,
                "picking_id": picking.id,
                "location_id": self.supplier.id,
                "location_dest_id": self.stock.id,
            }
        )
        picking.action_confirm()
        picking.action_assign()
        picking.move_line_ids.quantity = 5.0
        picking.move_ids.picked = True
        picking.button_validate()

        def notes():
            return self.env["mail.message"].search_count(
                [("model", "=", "stock.picking"), ("res_id", "=", picking.id)]
            )

        before = notes()
        line = picking.move_line_ids
        line.write({"location_dest_id": line.location_dest_id.id})
        self.assertEqual(before, notes(), "an unchanged value must not be logged")

        line.write({"location_dest_id": self.shelf_1.id})
        self.assertEqual(before + 1, notes(), "a real change must still be logged")

    def test_a_quantity_correction_keeps_fifo_order(self):
        product = self._product("FifoOrder", tracking="lot")
        lots = {}
        for name, in_date in (("OLD", "2020-01-01"), ("NEW", "2021-01-01")):
            lot = self.env["stock.lot"].create(
                {"name": "FIFO-%s" % name, "product_id": product.id}
            )
            lots[name] = lot
            move = self.env["stock.move"].create(
                {
                    "location_id": self.supplier.id,
                    "location_dest_id": self.stock.id,
                    "product_id": product.id,
                    "product_uom_id": product.uom_id.id,
                    "product_uom_qty": 10.0,
                }
            )
            move._action_confirm()
            move._action_assign()
            move.move_line_ids.lot_id = lot
            move.move_line_ids.quantity = 10.0
            move.picked = True
            move._action_done()
            lot.quant_ids.invalidate_recordset(["in_date"])
            self.env.cr.execute(
                "UPDATE stock_quant SET in_date = %s WHERE product_id = %s AND lot_id = %s",
                (in_date, product.id, lot.id),
            )
        self.env.invalidate_all()

        def first_lot_taken():
            out = self.env["stock.move"].create(
                {
                    "location_id": self.stock.id,
                    "location_dest_id": self.customer.id,
                    "product_id": product.id,
                    "product_uom_id": product.uom_id.id,
                    "product_uom_qty": 5.0,
                }
            )
            out._action_confirm()
            out._action_assign()
            taken = out.move_line_ids.lot_id
            out._do_unreserve()
            out._action_cancel()
            return taken

        self.assertEqual(first_lot_taken(), lots["OLD"])
        oldest_receipt = self.env["stock.move.line"].search(
            [("lot_id", "=", lots["OLD"].id), ("state", "=", "done")]
        )
        oldest_receipt.write({"quantity": 9.0})
        self.assertEqual(
            first_lot_taken(),
            lots["OLD"],
            "correcting a receipt must not reorder FIFO removal",
        )

    def test_a_quantity_correction_moves_only_the_difference(self):
        product = self._product("DeltaOnly")
        move = self._done_move(
            product, self.stock, self.customer, 3.0, seed_source=True
        )
        calls = []
        quant_model = type(self.env["stock.quant"])
        original = quant_model._update_available_quantity

        def spy(self, product_id, location_id, quantity=False, **kwargs):
            calls.append((location_id, quantity))
            return original(self, product_id, location_id, quantity=quantity, **kwargs)

        self.patch(quant_model, "_update_available_quantity", spy)
        move.move_line_ids.write({"quantity": 5.0})

        self.assertEqual(
            len(calls), 2, "an unchanged quant key needs one call per side, not four"
        )
        self.assertEqual(
            dict(calls),
            {self.stock: -2.0, self.customer: 2.0},
        )

    def test_writing_a_recordset_on_a_done_line_that_has_a_picking(self):
        product = self._product("RecordsetWrite", tracking="lot")
        lots = self.env["stock.lot"].create(
            [
                {"name": "RW-1", "product_id": product.id},
                {"name": "RW-2", "product_id": product.id},
            ]
        )
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.env.ref("stock.picking_type_in").id,
                "location_id": self.supplier.id,
                "location_dest_id": self.stock.id,
            }
        )
        self.env["stock.move"].create(
            {
                "product_id": product.id,
                "product_uom_id": product.uom_id.id,
                "product_uom_qty": 5.0,
                "picking_id": picking.id,
                "location_id": self.supplier.id,
                "location_dest_id": self.stock.id,
            }
        )
        picking.action_confirm()
        picking.action_assign()
        picking.move_line_ids.lot_id = lots[0]
        picking.move_line_ids.quantity = 5.0
        picking.move_ids.picked = True
        picking.button_validate()

        picking.move_line_ids.write({"lot_id": lots[1]})

        self.assertEqual(picking.move_line_ids.lot_id, lots[1])
        self.assertEqual(
            self.env["stock.quant"]._get_available_quantity(
                product, self.stock, lot_id=lots[1]
            ),
            5.0,
        )

    def test_adding_a_line_makes_a_move_that_cannot_reserve_ready(self):
        consumable = self.env["product.product"].create(
            {"name": "ReadyConsu", "is_storable": False, "type": "consu"}
        )
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.env.ref("stock.picking_type_out").id,
                "location_id": self.stock.id,
                "location_dest_id": self.customer.id,
            }
        )
        move = self.env["stock.move"].create(
            {
                "product_id": consumable.id,
                "product_uom_id": consumable.uom_id.id,
                "product_uom_qty": 10.0,
                "picking_id": picking.id,
                "location_id": self.stock.id,
                "location_dest_id": self.customer.id,
            }
        )
        picking.action_confirm()
        picking.action_assign()
        self.assertEqual(move.state, "assigned")

        move.move_line_ids.unlink()
        self.assertEqual(move.state, "confirmed")

        self.env["stock.move.line"].create(
            {
                "move_id": move.id,
                "picking_id": picking.id,
                "product_id": consumable.id,
                "product_uom_id": consumable.uom_id.id,
                "quantity": 10.0,
                "location_id": self.stock.id,
                "location_dest_id": self.customer.id,
            }
        )
        self.assertEqual(
            move.state,
            "assigned",
            "a line covering the demand must make the move ready even when"
            " its source needs no reservation",
        )
        self.assertEqual(picking.state, "assigned")

    def test_a_draft_move_is_only_promoted_when_the_line_reserves(self):
        product = self._product("DraftPromotion")
        self.env["stock.quant"]._update_available_quantity(product, self.stock, 10.0)
        draft_out = self.env["stock.picking"].create(
            {
                "picking_type_id": self.env.ref("stock.picking_type_out").id,
                "location_id": self.stock.id,
                "location_dest_id": self.customer.id,
            }
        )
        out_move = self.env["stock.move"].create(
            {
                "product_id": product.id,
                "product_uom_id": product.uom_id.id,
                "product_uom_qty": 1.0,
                "picking_id": draft_out.id,
                "location_id": self.stock.id,
                "location_dest_id": self.customer.id,
            }
        )
        self.assertEqual(out_move.state, "draft")
        self.env["stock.move.line"].create(
            {
                "move_id": out_move.id,
                "product_id": product.id,
                "product_uom_id": product.uom_id.id,
                "quantity": 1.0,
            }
        )
        self.assertEqual(out_move.state, "assigned")

        draft_in = self.env["stock.picking"].create(
            {
                "picking_type_id": self.env.ref("stock.picking_type_in").id,
                "location_id": self.supplier.id,
                "location_dest_id": self.stock.id,
            }
        )
        self.env["stock.move.line"].create(
            {
                "picking_id": draft_in.id,
                "product_id": product.id,
                "product_uom_id": product.uom_id.id,
                "quantity": 1.0,
                "location_id": self.supplier.id,
                "location_dest_id": self.stock.id,
            }
        )
        self.assertEqual(
            draft_in.move_ids.state,
            "draft",
            "a receipt reserves nothing, so its draft move must stay draft",
        )

    def test_a_move_split_across_packages_counts_its_demand_once(self):
        product = self._product("SplitDemand")
        self.env["stock.quant"]._update_available_quantity(product, self.stock, 100.0)
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.env.ref("stock.picking_type_out").id,
                "location_id": self.stock.id,
                "location_dest_id": self.customer.id,
            }
        )
        self.env["stock.move"].create(
            {
                "product_id": product.id,
                "product_uom_id": product.uom_id.id,
                "product_uom_qty": 10.0,
                "picking_id": picking.id,
                "location_id": self.stock.id,
                "location_dest_id": self.customer.id,
            }
        )
        picking.action_confirm()
        picking.action_assign()
        line = picking.move_line_ids
        line.quantity = 4.0
        second = line.copy({"quantity": 3.0})
        line.result_package_id = self.env["stock.package"].create({"name": "SD-1"})
        second.result_package_id = self.env["stock.package"].create({"name": "SD-2"})

        aggregated = picking.move_line_ids._get_aggregated_product_quantities()

        self.assertEqual(len(aggregated), 2)
        self.assertEqual(sum(line["quantity"] for line in aggregated.values()), 7.0)
        self.assertEqual(
            sum(line["qty_ordered"] for line in aggregated.values()),
            10.0,
            "the move's demand must be reported once, not once per package",
        )

    def test_a_single_key_aggregation_is_unchanged(self):
        product = self._product("SingleKeyDemand")
        self.env["stock.quant"]._update_available_quantity(product, self.stock, 100.0)
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.env.ref("stock.picking_type_out").id,
                "location_id": self.stock.id,
                "location_dest_id": self.customer.id,
            }
        )
        self.env["stock.move"].create(
            {
                "product_id": product.id,
                "product_uom_id": product.uom_id.id,
                "product_uom_qty": 10.0,
                "picking_id": picking.id,
                "location_id": self.stock.id,
                "location_dest_id": self.customer.id,
            }
        )
        picking.action_confirm()
        picking.action_assign()
        line = picking.move_line_ids
        line.quantity = 4.0
        line.copy({"quantity": 3.0})

        (aggregated,) = (
            picking.move_line_ids._get_aggregated_product_quantities().values()
        )

        self.assertEqual(aggregated["quantity"], 7.0)
        self.assertEqual(aggregated["qty_ordered"], 10.0)

    def test_correcting_many_lines_posts_one_note(self):
        product = self._product("BatchNote")
        self.env["stock.quant"]._update_available_quantity(product, self.stock, 500.0)
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.env.ref("stock.picking_type_out").id,
                "location_id": self.stock.id,
                "location_dest_id": self.customer.id,
            }
        )
        self.env["stock.move"].create(
            {
                "product_id": product.id,
                "product_uom_id": product.uom_id.id,
                "product_uom_qty": 20.0,
                "picking_id": picking.id,
                "location_id": self.stock.id,
                "location_dest_id": self.customer.id,
            }
        )
        picking.action_confirm()
        picking.action_assign()
        line = picking.move_line_ids
        line.quantity = 1.0
        for _index in range(19):
            line.copy({"quantity": 1.0})
        picking.move_ids.picked = True
        picking.button_validate()

        def notes():
            return self.env["mail.message"].search(
                [("model", "=", "stock.picking"), ("res_id", "=", picking.id)]
            )

        before = notes()
        picking.move_line_ids.write({"quantity": 2.0})
        posted = notes() - before

        self.assertEqual(
            len(posted), 1, "one write over 20 lines must post one note, not twenty"
        )
        body = posted.body
        for expected in ("BatchNote", "2.0"):
            self.assertIn(expected, body)
        self.assertEqual(
            body.count("BatchNote"),
            20,
            "the single note must still name every corrected line",
        )

    def test_the_quant_match_endpoint_returns_named_keys(self):
        product = self._product("QuantMatch")
        self.env["stock.quant"]._update_available_quantity(product, self.stock, 12.0)
        move = self.env["stock.move"].create(
            {
                "location_id": self.stock.id,
                "location_dest_id": self.customer.id,
                "product_id": product.id,
                "product_uom_id": product.uom_id.id,
                "product_uom_qty": 5.0,
            }
        )
        move._action_confirm()
        move._action_assign()
        line = move.move_line_ids

        match = move.move_line_ids.get_move_line_quant_match(move.id, line.ids, [])

        self.assertEqual(set(match), {"quants", "move_lines"})
        self.assertTrue(match["quants"], "the reserved quant must be reported")
        for quant in match["quants"]:
            self.assertEqual(set(quant), {"id", "available_quantity", "move_line_ids"})
        for reported in match["move_lines"]:
            self.assertEqual(set(reported), {"id", "quantity", "quant_id"})
        self.assertEqual([reported["id"] for reported in match["move_lines"]], line.ids)

    def test_the_quant_match_endpoint_is_empty_when_nothing_is_dirty(self):
        product = self._product("QuantMatchEmpty")
        move = self.env["stock.move"].create(
            {
                "location_id": self.stock.id,
                "location_dest_id": self.customer.id,
                "product_id": product.id,
                "product_uom_id": product.uom_id.id,
                "product_uom_qty": 5.0,
            }
        )
        move._action_confirm()

        match = self.env["stock.move.line"].get_move_line_quant_match(move.id, [], [])

        self.assertEqual(match, {"quants": [], "move_lines": []})

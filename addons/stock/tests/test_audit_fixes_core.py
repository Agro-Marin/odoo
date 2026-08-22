from odoo import Command
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from odoo.addons.stock.tests.common import TestStockCommon


@tagged("post_install", "-at_install")
class TestAuditFixesCore(TestStockCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Quant = cls.env["stock.quant"]
        cls.MoveLine = cls.env["stock.move.line"]
        cls.serial_product = cls.ProductObj.create(
            {
                "name": "Audit Serial Product",
                "is_storable": True,
                "tracking": "serial",
            }
        )

    def _spy_calls(self, module, klass, method):
        orig = getattr(klass, method)
        calls = {"n": 0}

        def spy(records, *args, **kwargs):
            calls["n"] += 1
            return orig(records, *args, **kwargs)

        setattr(klass, method, spy)
        self.addCleanup(setattr, klass, method, orig)
        return calls

    def _out_picking_with_moves(self, products, qty=5.0):
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.picking_type_out.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "move_ids": [
                    Command.create(
                        {
                            "product_id": p.id,
                            "product_uom_qty": qty,
                            "product_uom_id": p.uom_id.id,
                            "location_id": self.stock_location.id,
                            "location_dest_id": self.customer_location.id,
                        }
                    )
                    for p in products
                ],
            }
        )
        picking.action_confirm()
        return picking

    def _mto_chain(self, product, qty=5.0):
        receipt = self.env["stock.picking"].create(
            {
                "picking_type_id": self.picking_type_in.id,
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
                "move_ids": [
                    Command.create(
                        {
                            "product_id": product.id,
                            "product_uom_qty": qty,
                            "product_uom_id": product.uom_id.id,
                            "location_id": self.supplier_location.id,
                            "location_dest_id": self.stock_location.id,
                        }
                    )
                ],
            }
        )
        receipt.action_confirm()
        m_in = receipt.move_ids
        m_in.quantity = qty
        m_in.picked = True
        m_in._action_done()
        self.assertEqual(m_in.state, "done")

        m_out = self.env["stock.move"].create(
            {
                "product_id": product.id,
                "product_uom_qty": qty,
                "product_uom_id": product.uom_id.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "picking_type_id": self.picking_type_out.id,
                "procure_method": "make_to_order",
                "move_orig_ids": [Command.link(m_in.id)],
            }
        )
        m_out._action_confirm()
        m_out._action_assign()
        self.assertEqual(m_out.state, "assigned")
        self.assertEqual(m_out.move_line_ids.quantity, qty)
        return m_in, m_out

    def _force_outgoing_done(self, product, qty):
        move = self.env["stock.move"].create(
            {
                "product_id": product.id,
                "product_uom_qty": qty,
                "product_uom_id": product.uom_id.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "picking_type_id": self.picking_type_out.id,
            }
        )
        move._action_confirm()
        move.quantity = qty
        move.picked = True
        move._action_done()
        return move

    def test_duplicate_serial_onchange_warns_on_first_duplicate(self):
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.picking_type_in.id,
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
                "move_ids": [
                    Command.create(
                        {
                            "product_id": self.serial_product.id,
                            "product_uom_qty": 2.0,
                            "product_uom_id": self.serial_product.uom_id.id,
                            "location_id": self.supplier_location.id,
                            "location_dest_id": self.stock_location.id,
                        }
                    )
                ],
            }
        )
        picking.action_confirm()
        move = picking.move_ids
        line1, line2 = self.MoveLine.create(
            [
                {
                    "move_id": move.id,
                    "picking_id": picking.id,
                    "product_id": self.serial_product.id,
                    "quantity": 1.0,
                    "lot_name": "AUD-SN-1",
                },
                {
                    "move_id": move.id,
                    "picking_id": picking.id,
                    "product_id": self.serial_product.id,
                    "quantity": 1.0,
                    "lot_name": "AUD-SN-1",
                },
            ]
        )
        res = line2._onchange_serial_number()
        self.assertTrue(
            res.get("warning"),
            "first duplicate serial must trigger the onchange warning",
        )
        line1.lot_name = "AUD-SN-UNIQUE"
        res = line1._onchange_serial_number()
        self.assertFalse(res.get("warning"))

    def test_picking_assignation_reference_set_coverage(self):
        ref1, ref2, ref3 = self.env["stock.reference"].create(
            [{"name": "AUD-REF-1"}, {"name": "AUD-REF-2"}, {"name": "AUD-REF-3"}]
        )

        def make_move(product, refs):
            return self.env["stock.move"].create(
                {
                    "product_id": product.id,
                    "product_uom_qty": 1.0,
                    "product_uom_id": product.uom_id.id,
                    "location_id": self.stock_location.id,
                    "location_dest_id": self.customer_location.id,
                    "picking_type_id": self.picking_type_out.id,
                    "reference_ids": [Command.set(refs.ids)],
                }
            )

        move_a = make_move(self.productA, ref1 | ref2)
        move_a._action_confirm()
        picking_ab = move_a.picking_id
        self.assertTrue(picking_ab)

        move_b = make_move(self.productA, ref1)
        move_b._action_confirm()
        self.assertTrue(move_b.picking_id)
        self.assertNotEqual(
            move_b.picking_id,
            picking_ab,
            "a move must not join a picking serving references it does not carry",
        )

        move_c = make_move(self.productB, ref1 | ref2)
        move_c._action_confirm()
        self.assertEqual(move_c.picking_id, picking_ab)

        move_d = make_move(self.productB, ref1 | ref3)
        move_d._action_confirm()
        self.assertEqual(move_d.picking_id, move_b.picking_id)

    def _gather_spy(self):
        import odoo.addons.stock.models.stock_quant as _sq

        return self._spy_calls(_sq, _sq.StockQuant, "_gather"), None

    def test_update_reserved_quantity_single_gather(self):
        self.Quant._update_available_quantity(self.productC, self.stock_location, 20.0)
        self.env.flush_all()
        calls, _ = self._gather_spy()
        self.Quant._update_reserved_quantity(self.productC, self.stock_location, 2.0)
        self.assertEqual(
            calls["n"], 1, "reservation update must gather once, not re-gather"
        )

    def test_action_assign_gather_scaling(self):
        n = 6
        products = self.ProductObj.create(
            [{"name": f"aud-scale-{i}", "is_storable": True} for i in range(n)]
        )
        for product in products:
            self.Quant._update_available_quantity(product, self.stock_location, 50.0)
        picking = self._out_picking_with_moves(products)
        self.env.flush_all()
        calls, _ = self._gather_spy()
        picking.action_assign()
        self.assertEqual({"assigned"}, set(picking.move_ids.mapped("state")))
        self.assertLessEqual(
            calls["n"],
            2 * n + 2,
            "reservation must not re-gather availability per created line",
        )

    def test_reserve_new_move_lines_grouped(self):
        import odoo.addons.stock.models.stock_quant as _sq

        self.Quant._update_available_quantity(self.productE, self.stock_location, 10.0)
        move = self.env["stock.move"].create(
            {
                "product_id": self.productE.id,
                "product_uom_qty": 6.0,
                "product_uom_id": self.productE.uom_id.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "picking_type_id": self.picking_type_out.id,
            }
        )
        move._action_confirm()
        calls = self._spy_calls(_sq, _sq.StockQuant, "_update_reserved_quantity")
        self.MoveLine.create(
            [
                {"move_id": move.id, "product_id": self.productE.id, "quantity": 2.0},
                {"move_id": move.id, "product_id": self.productE.id, "quantity": 2.0},
                {"move_id": move.id, "product_id": self.productE.id, "quantity": 2.0},
            ]
        )
        self.assertEqual(
            calls["n"], 1, "same-characteristics lines must reserve in one update"
        )
        quant = self.Quant._gather(self.productE, self.stock_location, strict=True)
        self.assertAlmostEqual(sum(quant.mapped("reserved_quantity")), 6.0)
        self.assertEqual(move.state, "assigned")

    def test_write_location_dest_does_not_resync_reservation(self):
        import odoo.addons.stock.models.stock_move_line as _sml

        self.Quant._update_available_quantity(self.productB, self.stock_location, 5.0)
        picking = self._out_picking_with_moves(self.productB)
        picking.action_assign()
        line = picking.move_line_ids
        self.assertEqual(line.quantity, 5.0)
        quant = self.Quant._gather(self.productB, self.stock_location, strict=True)
        self.assertAlmostEqual(sum(quant.mapped("reserved_quantity")), 5.0)

        calls = self._spy_calls(_sml, _sml.StockMoveLine, "_synchronize_quant")
        line.location_dest_id = self.pack_location
        self.assertEqual(
            calls["n"],
            0,
            "a destination-side write must not unreserve/re-reserve the line",
        )
        self.assertAlmostEqual(sum(quant.mapped("reserved_quantity")), 5.0)

    def test_free_reservation_partial_keeps_mto_chain(self):
        m_in, m_out = self._mto_chain(self.productD, qty=5.0)
        self._force_outgoing_done(self.productD, 3.0)
        self.assertAlmostEqual(m_out.move_line_ids.quantity, 2.0)
        self.assertEqual(m_out.procure_method, "make_to_stock")
        self.assertEqual(
            m_out.move_orig_ids,
            m_in,
            "a partially-reduced reservation must not sever the origin chain",
        )

    def test_free_reservation_full_unlink_severs_chain(self):
        _m_in, m_out = self._mto_chain(self.productD, qty=5.0)
        self._force_outgoing_done(self.productD, 5.0)
        self.assertFalse(m_out.move_line_ids)
        self.assertEqual(m_out.procure_method, "make_to_stock")
        self.assertFalse(m_out.move_orig_ids)

    def test_same_package_validation_scoped_zero_quant_cleanup(self):
        package = self.env["stock.package"].create({"name": "AUD-PACK"})
        self.Quant._update_available_quantity(
            self.productC, self.stock_location, 5.0, package_id=package
        )
        unrelated_zero = self.Quant.create(
            {
                "product_id": self.productD.id,
                "location_id": self.shelf_2.id,
                "quantity": 0.0,
            }
        )
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.picking_type_int.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.shelf_1.id,
                "move_ids": [
                    Command.create(
                        {
                            "product_id": self.productC.id,
                            "product_uom_qty": 5.0,
                            "product_uom_id": self.productC.uom_id.id,
                            "location_id": self.stock_location.id,
                            "location_dest_id": self.shelf_1.id,
                        }
                    )
                ],
            }
        )
        picking.action_confirm()
        picking.action_assign()
        line = picking.move_line_ids
        self.assertEqual(line.package_id, package)
        line.result_package_id = package
        line.picked = True
        picking.move_ids._action_done()

        self.assertFalse(
            self.Quant.search(
                [
                    ("product_id", "=", self.productC.id),
                    ("location_id", "=", self.stock_location.id),
                ]
            ),
            "in-scope zero quants of the validated transfer must be cleaned",
        )
        self.assertTrue(
            unrelated_zero.exists(),
            "the cleanup must stay scoped to the touched products/locations",
        )

    def test_done_lines_batch_single_reassign(self):
        import odoo.addons.stock.models.stock_move as _sm

        self.Quant._update_available_quantity(self.productE, self.stock_location, 10.0)
        m1 = self.env["stock.move"].create(
            {
                "product_id": self.productE.id,
                "product_uom_qty": 4.0,
                "product_uom_id": self.productE.uom_id.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.pack_location.id,
                "picking_type_id": self.picking_type_int.id,
            }
        )
        m1._action_confirm()
        m1.quantity = 4.0
        m1.picked = True
        m1._action_done()
        m2 = self.env["stock.move"].create(
            {
                "product_id": self.productE.id,
                "product_uom_qty": 6.0,
                "product_uom_id": self.productE.uom_id.id,
                "location_id": self.pack_location.id,
                "location_dest_id": self.customer_location.id,
                "picking_type_id": self.picking_type_out.id,
                "procure_method": "make_to_order",
                "move_orig_ids": [Command.link(m1.id)],
            }
        )
        m2._action_confirm()
        m2._action_assign()

        calls = self._spy_calls(_sm, _sm.StockMove, "_do_unreserve")
        self.MoveLine.create(
            [
                {
                    "move_id": m1.id,
                    "product_id": self.productE.id,
                    "quantity": 1.0,
                    "picked": True,
                },
                {
                    "move_id": m1.id,
                    "product_id": self.productE.id,
                    "quantity": 1.0,
                    "picked": True,
                },
            ]
        )
        self.assertEqual(
            calls["n"],
            1,
            "N done lines on one move must reassign the chained moves once",
        )
        self.assertAlmostEqual(
            sum(m2.move_line_ids.mapped("quantity_product_uom")), 6.0
        )

    def test_compute_picked_ignores_context(self):
        self.Quant._update_available_quantity(self.productB, self.stock_location, 5.0)
        picking = self._out_picking_with_moves(self.productB, qty=2.0)
        self.assertFalse(picking.move_ids.picked)
        line = self.MoveLine.with_context(auto_pick_move_lines=True).create(
            {
                "picking_id": picking.id,
                "product_id": self.productB.id,
                "product_uom_id": self.productB.uom_id.id,
                "quantity": 1.0,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
            }
        )
        self.assertFalse(
            line.picked,
            "picked must derive from state/move, never from the environment",
        )

    def test_action_show_details_sets_picked_default(self):
        picking = self._out_picking_with_moves(self.productB, qty=1.0)
        move = picking.move_ids
        move.picked = True
        action = move.action_show_details()
        self.assertTrue(action["context"].get("default_picked"))
        self.assertNotIn("auto_pick_move_lines", action["context"])
        move.picked = False
        self.assertFalse(move.action_show_details()["context"].get("default_picked"))

    def test_get_reserve_quantity_non_positive_returns_empty(self):
        self.Quant._update_available_quantity(self.productA, self.stock_location, 4.0)
        self.assertEqual(
            self.Quant._get_reserve_quantity(self.productA, self.stock_location, 0.0),
            [],
        )
        self.assertEqual(
            self.Quant._get_reserve_quantity(self.productA, self.stock_location, -1.0),
            [],
        )

    def test_apply_inventory_missing_loss_location_raises(self):
        self.env["ir.default"].search(
            [
                ("field_id.model", "=", "product.template"),
                ("field_id.name", "=", "property_stock_inventory"),
            ]
        ).unlink()
        product = self.ProductObj.create(
            {"name": "aud-no-loss-loc", "is_storable": True}
        )
        self.assertFalse(product.property_stock_inventory)
        quant = self.Quant.create(
            {
                "product_id": product.id,
                "location_id": self.stock_location.id,
                "quantity": 2.0,
            }
        )
        quant.inventory_quantity = 5.0
        with self.assertRaises(UserError):
            quant._apply_inventory()

    def test_batch_create_duplicate_serials_clean_error(self):
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.picking_type_in.id,
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
                "move_ids": [
                    Command.create(
                        {
                            "product_id": self.serial_product.id,
                            "product_uom_qty": 2.0,
                            "product_uom_id": self.serial_product.uom_id.id,
                            "location_id": self.supplier_location.id,
                            "location_dest_id": self.stock_location.id,
                        }
                    )
                ],
            }
        )
        picking.action_confirm()
        move = picking.move_ids
        mls = self.MoveLine.create(
            [
                {
                    "move_id": move.id,
                    "product_id": self.serial_product.id,
                    "quantity": 1.0,
                    "lot_name": "AUD-SN-DUP",
                },
                {
                    "move_id": move.id,
                    "product_id": self.serial_product.id,
                    "quantity": 1.0,
                    "lot_name": "AUD-SN-DUP",
                },
            ]
        )
        with self.assertRaises(ValidationError):
            mls._create_and_assign_production_lot()

    def test_generate_lot_vals_count_bound(self):
        from odoo.addons.stock.models.stock_move import GENERATED_LOT_VALS_MAX

        context_data = {
            "default_product_id": self.serial_product.id,
            "default_tracking": "serial",
            "default_location_dest_id": self.stock_location.id,
        }
        with self.assertRaises(UserError):
            self.env["stock.move"].action_generate_lot_line_vals(
                context_data,
                "generate",
                "SN0001",
                GENERATED_LOT_VALS_MAX + 1,
                False,
            )

    def test_generate_lot_vals_sequence_never_rewinds(self):
        sequence = self.env["ir.sequence"].create(
            {
                "name": "aud-lot-seq",
                "implementation": "standard",
                "padding": 5,
                "number_increment": 5,
                "number_next_actual": 50,
            }
        )
        self.serial_product.product_tmpl_id.lot_sequence_id = sequence
        first_lot = sequence.get_next_char(45)
        context_data = {
            "default_product_id": self.serial_product.id,
            "default_tracking": "serial",
            "default_location_dest_id": self.stock_location.id,
        }
        self.env["stock.move"].action_generate_lot_line_vals(
            context_data, "generate", first_lot, 1, False
        )
        current = sequence._get_current_sequence()
        self.assertGreaterEqual(
            current.number_next_actual,
            50,
            "a client-steered generation must never rewind the lot sequence",
        )

    def test_delivery_slip_aggregation_no_prefix_collision(self):
        self.Quant._update_available_quantity(self.productB, self.stock_location, 4.0)
        picking = self._out_picking_with_moves(self.productB, qty=4.0)
        move1 = picking.move_ids
        move1.description_picking = "AUD-AGG"
        base_key = self.MoveLine._get_aggregated_properties(move=move1)["line_key"]
        tail = base_key.split("AUD-AGG", 1)[1]
        move1.description_picking = "AUD-AGG" + tail + "_X"

        move2 = self.env["stock.move"].create(
            {
                "product_id": self.productB.id,
                "product_uom_qty": 5.0,
                "product_uom_id": self.productB.uom_id.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.customer_location.id,
                "picking_id": picking.id,
                "description_picking": "AUD-AGG",
            }
        )
        move2._action_confirm()
        move2._action_cancel()
        picking.action_assign()
        self.assertEqual(move1.move_line_ids.quantity, 4.0)

        aggregated = picking.move_line_ids._get_aggregated_product_quantities()
        values_by_desc = {vals["description"]: vals for vals in aggregated.values()}
        self.assertIn(
            "AUD-AGG",
            values_by_desc,
            "the cancelled move must keep its own aggregation entry",
        )
        self.assertAlmostEqual(values_by_desc["AUD-AGG"]["qty_ordered"], 5.0)
        move1_desc = move1.description_picking
        self.assertAlmostEqual(
            values_by_desc[move1_desc]["qty_ordered"],
            4.0,
            msg="the cancelled move's demand must not leak into a prefix-colliding group",
        )

    def test_draft_incoming_forecast_uses_incoming_key(self):
        self.Quant._update_available_quantity(self.productD, self.stock_location, 7.0)
        move = self.env["stock.move"].create(
            {
                "product_id": self.productD.id,
                "product_uom_qty": 0.0,
                "product_uom_id": self.productD.uom_id.id,
                "location_id": self.supplier_location.id,
                "location_dest_id": self.stock_location.id,
                "picking_type_id": self.picking_type_in.id,
            }
        )
        self.assertEqual(move.state, "draft")
        self.assertAlmostEqual(
            move.forecast_availability,
            7.0,
            msg="a draft incoming move must read the incoming forecast key, "
            "not shortcut through the (unprefetched) outgoing one",
        )


@tagged("post_install", "-at_install")
class TestAuditQuantTasksScope(TestStockCommon):
    def test_quant_tasks_propagates_recordset(self):
        from odoo.addons.stock.models import stock_quant as _sq

        product = self.env["product.product"].create(
            {"name": "QT Scope Product", "is_storable": True},
        )
        warehouse = self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.company.id)],
            limit=1,
        )
        self.env["stock.quant"]._update_available_quantity(
            product,
            warehouse.lot_stock_id,
            quantity=3,
        )
        quant = self.env["stock.quant"].search(
            [("product_id", "=", product.id)],
            limit=1,
        )
        seen_sizes = []
        orig = _sq.StockQuant._merge_quants

        def spy(records, *args, **kwargs):
            seen_sizes.append(len(records))
            return orig(records, *args, **kwargs)

        _sq.StockQuant._merge_quants = spy
        self.addCleanup(setattr, _sq.StockQuant, "_merge_quants", orig)

        quant._quant_tasks()
        self.assertEqual(
            seen_sizes,
            [1],
            "a recordset call must reach the scoped tasks with its records",
        )
        self.env["stock.quant"]._quant_tasks()
        self.assertEqual(
            seen_sizes,
            [1, 0],
            "a model-level call must stay global (empty recordset)",
        )

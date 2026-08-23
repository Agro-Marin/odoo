"""Regression tests for the `mrp` layer of `stock.move`.

Every test here was run against the commit before its fix and fails there; a
regression test that passes on the broken code is worth nothing.
"""

from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import TestMrpCommon


@tagged("post_install", "-at_install")
class TestStockMoveAudit(TestMrpCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.stock_location = cls.env.ref("stock.stock_location_stock")
        cls.finished = cls.env["product.product"].create(
            {"name": "Audit Finished", "is_storable": True}
        )

    def _make_product(self, name, **vals):
        return self.env["product.product"].create(
            {"name": name, "is_storable": True, **vals}
        )

    def _make_bom(self, product, components, byproducts=(), bom_type="normal", qty=1.0):
        return self.env["mrp.bom"].create(
            {
                "product_tmpl_id": product.product_tmpl_id.id,
                "product_qty": qty,
                "type": bom_type,
                "bom_line_ids": [
                    Command.create(
                        {"product_id": component.id, "product_qty": line_qty}
                    )
                    for component, line_qty in components
                ],
                "byproduct_ids": [
                    Command.create({"product_id": product_, "product_qty": line_qty})
                    for product_, line_qty in byproducts
                ],
            }
        )

    def _confirmed_order(self, bom, qty=1.0):
        production = self.env["mrp.production"].create(
            {
                "product_id": bom.product_tmpl_id.product_variant_id.id,
                "bom_id": bom.id,
                "product_qty": qty,
            }
        )
        production.action_confirm()
        return production

    # A move that carries both sides carries the same order on both

    def test_a_move_carrying_both_sides_names_one_order(self):
        component = self._make_product("Audit One Side Component")
        bom = self._make_bom(self.finished, [(component, 1.0)])
        production = self._confirmed_order(bom)
        other = self._confirmed_order(bom)
        raw_move = production.move_raw_ids

        # Both sides pointing at the same order is a shape the tree produces --
        # scrapping a component, moving an output into the component list -- and
        # `_get_production` is free to answer with either.
        raw_move.production_id = production.id
        self.env.flush_all()
        self.assertEqual(raw_move._get_production(), production)

        with self.assertRaises(
            Exception,
            msg="a move that is a component of one order and an output of another "
            "has no single answer to `_get_production`, and every call site that "
            "spells the choice as an `or` would disagree with the ones that spell "
            "it the other way round",
        ):
            with self.env.cr.savepoint():
                raw_move.production_id = other.id
                self.env.flush_all()

    # Changing a by-product must not delete the record the caller holds

    def test_changing_a_by_product_keeps_the_move_the_caller_was_given(self):
        component = self._make_product("Audit Swap Component")
        first = self._make_product("Audit By-product First")
        second = self._make_product("Audit By-product Second")
        bom = self._make_bom(
            self.finished, [(component, 1.0)], byproducts=[(first.id, 1.0)]
        )
        production = self._confirmed_order(bom)
        by_product_move = production.move_finished_ids.filtered(
            lambda move: move.product_id == first
        )
        move_id = by_product_move.id

        by_product_move.write({"product_id": second.id})
        self.env.flush_all()

        self.assertTrue(
            by_product_move.exists(),
            "`write` used to replace the move and unlink the original, which left "
            "every caller further up the MRO holding a deleted id -- `sale_stock`'s "
            "own `write` iterates `self` right after `super()` and died there",
        )
        self.assertEqual(by_product_move.id, move_id)
        self.assertEqual(by_product_move.product_id, second)
        self.assertEqual(
            by_product_move.move_line_ids.product_id,
            by_product_move.move_line_ids and second,
            "the move lines still have to follow the product, which is what the "
            "replace-the-move version was written for",
        )

    # A cancelled component requires nothing, so it cannot hold the order back

    def test_a_cancelled_component_does_not_hold_the_order_back(self):
        kept = self._make_product("Audit Kept Component")
        cancelled = self._make_product("Audit Cancelled Component")
        bom = self._make_bom(self.finished, [(kept, 1.0), (cancelled, 1.0)])

        states = {}
        for drop in ("delete", "cancel"):
            production = self._confirmed_order(bom, qty=10.0)
            # Exactly one unit, in the order's own source location: enough for the
            # single unit being produced, not enough for the whole order, so the
            # move sits at `partially_available` and `super()` reaches the branch
            # this test is about.
            self.env["stock.quant"]._update_available_quantity(
                kept, production.location_src_id, 1
            )
            self.env.flush_all()
            doomed = production.move_raw_ids.filtered(
                lambda move, cancelled=cancelled: move.product_id == cancelled
            )
            if drop == "delete":
                doomed.unlink()
            else:
                doomed._action_cancel()
            production.move_raw_ids._action_assign()
            production.qty_producing = 1.0
            self.env.flush_all()
            self.env.invalidate_all()
            states[drop] = production.reservation_state

        self.assertEqual(
            states["delete"],
            "assigned",
            "the surviving component covers the quantity being produced",
        )
        self.assertEqual(
            states["cancel"],
            states["delete"],
            "a cancelled component asks for nothing and `super()` already leaves it "
            "out; judging the lift over `self` let it veto the same order that "
            "reads Ready without it",
        )

    # "Manual consumption" means the recorded quantity differs from the demand

    def test_a_quantity_that_matches_the_demand_is_not_a_manual_edit(self):
        component = self._make_product("Audit Rounding Component")
        bom = self._make_bom(self.finished, [(component, 1.0)])
        production = self._confirmed_order(bom)
        raw_move = production.move_raw_ids
        uom = raw_move.product_uom_id

        demand = raw_move.product_uom_qty
        # A quantity one bit away from the demand and equal to it at the unit's
        # precision -- what a UoM round-trip produces.
        recorded = demand - 1e-15
        self.assertEqual(
            uom.compare(demand, recorded),
            0,
            "this test measures nothing unless the two are the same quantity",
        )
        raw_move.manual_consumption = False
        self.env.flush_all()

        raw_move.with_context(force_manual_consumption=True).write(
            {"quantity": recorded}
        )

        self.assertFalse(
            raw_move.manual_consumption,
            "`!=` on two floats answered yes for quantities that are the same to "
            "the unit's precision",
        )

        raw_move.manual_consumption = False
        self.env.flush_all()
        raw_move.with_context(force_manual_consumption=True).write(
            {"quantity": demand + 1.0}
        )
        self.assertTrue(
            raw_move.manual_consumption,
            "a genuinely different quantity is still a manual edit",
        )

    # A kit component is numbered the same however it is read

    def test_kit_components_are_numbered_the_same_alone_or_together(self):
        kit = self._make_product("Audit Kit")
        components = [self._make_product("Audit Kit C%d" % i) for i in range(3)]
        self._make_bom(
            kit, [(component, 1.0) for component in components], bom_type="phantom"
        )
        picking_type = self.env["stock.picking.type"].search(
            [("code", "=", "outgoing"), ("company_id", "=", self.env.company.id)],
            limit=1,
        )
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": picking_type.id,
                "move_ids": [
                    Command.create(
                        {
                            "product_id": kit.id,
                            "product_uom_qty": 1.0,
                            "location_id": self.stock_location.id,
                            "location_dest_id": self.env.ref(
                                "stock.stock_location_customers"
                            ).id,
                        }
                    )
                ],
            }
        )
        picking.action_confirm()
        moves = picking.move_ids.sorted("id")
        # `action_explode` writes `description_picking`, which fires its inverse and
        # pins `description_picking_manual`, so this path carries no numbering at
        # all. Number them by hand through the procurement path's own compute.
        moves.description_picking_manual = False
        self.env.flush_all()
        self.env.invalidate_all()

        together = moves.mapped("description_picking")
        self.assertEqual(
            [description.rsplit(" - ", 1)[-1] for description in together],
            ["1/3", "2/3", "3/3"],
            "numbering counted the moves that happened to share the compute batch. "
            "It is not only unstable -- read one at a time, which is how a "
            "non-stored compute is served after an invalidation, every component "
            "of the kit called itself 1 of 1",
        )

        for index, move in enumerate(moves):
            self.env.invalidate_all()
            alone = self.env["stock.move"].browse(move.id).description_picking
            self.assertEqual(
                alone,
                together[index],
                "and the answer must not depend on how many siblings the reader "
                "happened to ask for",
            )

    # `should_consume_qty` follows every field its formula reads

    def test_should_consume_qty_follows_the_quantity_already_produced(self):
        component = self._make_product("Audit Consume Component")
        bom = self._make_bom(self.finished, [(component, 2.0)])
        production = self._confirmed_order(bom, qty=10.0)
        raw_move = production.move_raw_ids

        production.qty_producing = 5.0
        cached = raw_move.should_consume_qty

        finished_move = production.move_finished_ids.filtered(
            lambda move: move.product_id == production.product_id
        )
        finished_move.quantity = 4.0
        finished_move.picked = True
        self.env.flush_all()

        after_write = raw_move.should_consume_qty
        self.env.invalidate_all()
        truth = raw_move.should_consume_qty

        self.assertNotEqual(
            cached, truth, "the produced quantity has to move the answer at all"
        )
        self.assertEqual(
            after_write,
            truth,
            "the formula reads `unit_factor` and `qty_produced`; neither was "
            "declared, and the field is not stored, so a value cached before "
            "either moved survived the transaction",
        )

    # One formula for "what the order still expects of this move"

    def test_the_quantity_to_process_has_one_definition(self):
        component = self._make_product("Audit Formula Component")
        bom = self._make_bom(self.finished, [(component, 3.0)])
        production = self._confirmed_order(bom, qty=8.0)
        raw_move = production.move_raw_ids
        production.qty_producing = 2.0

        self.assertEqual(
            raw_move._get_qty_to_process(),
            raw_move.should_consume_qty,
            "`should_consume_qty` is this formula for a component",
        )
        self.assertEqual(
            raw_move._get_qty_to_process(),
            raw_move.product_uom_id.round(
                (production.qty_producing - production.qty_produced)
                * raw_move.unit_factor
            ),
        )

    # Cancelling two outputs of one order reports both

    def test_cancelling_two_outputs_of_one_order_reports_both(self):
        component = self._make_product("Audit Log Component")
        by_product = self._make_product("Audit Log By-product")
        bom = self._make_bom(
            self.finished, [(component, 1.0)], byproducts=[(by_product.id, 1.0)]
        )
        production = self._confirmed_order(bom, qty=5.0)
        outputs = production.move_finished_ids

        picking_type = self.env["stock.picking.type"].search(
            [("code", "=", "outgoing"), ("company_id", "=", self.env.company.id)],
            limit=1,
        )
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": picking_type.id,
                "move_ids": [
                    Command.create(
                        {
                            "product_id": output.product_id.id,
                            "product_uom_qty": 1.0,
                            "location_id": self.stock_location.id,
                            "location_dest_id": self.env.ref(
                                "stock.stock_location_customers"
                            ).id,
                            "move_orig_ids": [Command.set(output.ids)],
                        }
                    )
                    for output in outputs
                ],
            }
        )
        picking.action_confirm()

        reported = []
        original = type(self.env["mixin.stock.activity"])._log_activity

        def capture(records, render_method, documents):
            reported.extend(sorted(context.ids) for context in documents.values())
            return original(records, render_method, documents)

        self.patch(type(self.env["mixin.stock.activity"]), "_log_activity", capture)
        picking.move_ids._action_cancel()

        self.assertEqual(
            [sorted(picking.move_ids.ids)],
            reported,
            "both outputs of one order reach the same key, and plain assignment "
            "let the second drop the first's cancellations from the note",
        )

    # Neither hot path scales its reads with the number of records

    def test_exploding_kits_does_not_scale_the_bom_lookup(self):
        def confirm_kits(count, tag):
            kits = []
            for index in range(count):
                kit = self._make_product("Audit %s Kit %d" % (tag, index))
                component = self._make_product("Audit %s C %d" % (tag, index))
                self._make_bom(kit, [(component, 1.0)], bom_type="phantom")
                kits.append(kit)
            picking_type = self.env["stock.picking.type"].search(
                [("code", "=", "outgoing"), ("company_id", "=", self.env.company.id)],
                limit=1,
            )
            picking = self.env["stock.picking"].create(
                {
                    "picking_type_id": picking_type.id,
                    "move_ids": [
                        Command.create(
                            {
                                "product_id": kit.id,
                                "product_uom_qty": 1.0,
                                "location_id": self.stock_location.id,
                                "location_dest_id": self.env.ref(
                                    "stock.stock_location_customers"
                                ).id,
                            }
                        )
                        for kit in kits
                    ],
                }
            )
            self.env.flush_all()
            self.env.invalidate_all()
            calls = []
            bom_model = type(self.env["mrp.bom"])
            find = bom_model._bom_find

            def counted(records, products, **kwargs):
                calls.append(len(products))
                return find(records, products, **kwargs)

            self.patch(bom_model, "_bom_find", counted)
            picking.action_confirm()
            self.env.flush_all()
            return len(calls)

        few = confirm_kits(2, "Few")
        many = confirm_kits(10, "Many")

        # `explode()` legitimately looks up one BoM per kit it walks, so the count
        # cannot be flat. What must not scale is `action_explode`'s own lookup,
        # which used to add two further calls per move on top of that.
        self.assertLessEqual(
            many - few,
            10 - 2,
            "`_bom_find` takes a recordset and returns a dict -- it is built to be "
            "asked once. Asked once per move it cost three calls per kit instead "
            "of one (measured: %d calls for 2 kits, %d for 10)" % (few, many),
        )

    def test_creating_moves_for_many_orders_reads_the_orders_once(self):
        component = self._make_product("Audit Batch Component")
        bom = self._make_bom(self.finished, [(component, 2.0)])

        def create_for(count):
            productions = self.env["mrp.production"].create(
                [
                    {
                        "product_id": self.finished.id,
                        "bom_id": bom.id,
                        "product_qty": 1.0,
                    }
                    for _ in range(count)
                ]
            )
            productions.action_confirm()
            vals_list = [
                {
                    "product_id": component.id,
                    "product_uom_qty": 1.0,
                    "raw_material_production_id": production.id,
                }
                for production in productions
            ]
            self.env.flush_all()
            self.env.invalidate_all()
            before = self.env.cr.sql_log_count
            self.env["stock.move"].create(vals_list)
            self.env.flush_all()
            return self.env.cr.sql_log_count - before

        few = create_for(2)
        many = create_for(20)

        # `create` itself does some per-move work whatever we do here, so the count
        # cannot be flat either. What must not appear is the extra round trip per
        # *order* that browsing each one alone was paying.
        self.assertLess(
            many - few,
            2 * (20 - 2),
            "browsing each order on its own gave it a prefetch set of one, so the "
            "six reads in `create` cost a round trip per order (measured: %d "
            "queries for 2 orders, %d for 20)" % (few, many),
        )

    def test_a_negative_consumption_is_refused(self):
        component = self._make_product("Audit Negative Component")
        bom = self._make_bom(self.finished, [(component, 1.0)])
        production = self._confirmed_order(bom)
        with self.assertRaises(ValidationError):
            production.move_raw_ids.quantity = -1.0

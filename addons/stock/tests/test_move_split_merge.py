from unittest.mock import patch

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.base.models.ir_model_common import MODULE_UNINSTALL_FLAG
from odoo.addons.stock.const import CONTEXT_BLOCK_COMPLETING, is_internal_flag


@tagged("post_install", "-at_install")
class TestMoveSplitMergeEdgeCases(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.wh = cls.env["stock.warehouse"].search([], limit=1)
        cls.stock = cls.wh.lot_stock_id
        cls.output = cls.wh.wh_output_stock_loc_id
        cls.supplier = cls.env.ref("stock.stock_location_suppliers")
        cls.customer = cls.env.ref("stock.stock_location_customers")
        cls.unit = cls.env.ref("uom.product_uom_unit")
        cls.dozen = cls.env.ref("uom.product_uom_dozen")
        cls.Move = cls.env["stock.move"]

    def _product(self, name, qty=0.0, **kw):
        product = self.env["product.product"].create(
            {"name": name, "is_storable": True, **kw},
        )
        if qty:
            self.env["stock.quant"]._update_available_quantity(product, self.stock, qty)
        return product

    def _delivery(self, products, qty=5.0, **move_kw):
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.wh.out_type_id.id,
                "location_id": self.stock.id,
                "location_dest_id": self.customer.id,
                "move_ids": [
                    Command.create(
                        {
                            "product_id": product.id,
                            "product_uom_qty": qty,
                            "location_id": self.stock.id,
                            "location_dest_id": self.customer.id,
                            **move_kw,
                        },
                    )
                    for product in products
                ],
            },
        )
        picking.action_confirm()
        picking.action_assign()
        return picking

    def _statements(self, function):
        self.env.flush_all()
        before = self.env.cr.sql_statement_count
        function()
        self.env.flush_all()
        return self.env.cr.sql_statement_count - before

    def test_backorder_of_a_dozen_move_splits_what_the_lines_left(self):
        product = self._product("bo-dozen", 100, uom_ids=[(4, self.dozen.id)])
        picking = self._delivery(product, qty=1, product_uom_id=self.dozen.id)
        move = picking.move_ids
        move.move_line_ids.write(
            {"quantity": 4, "product_uom_id": self.unit.id, "picked": True},
        )

        picking._action_done()

        backorder = picking.backorder_ids
        self.assertEqual(move.move_line_ids.quantity_product_uom, 4)
        self.assertEqual(
            sum(backorder.move_ids.mapped("product_qty")),
            8,
            "4 units of 12 done leave 8, not the 8.04 read back from 0.67 dozen",
        )
        backorder.action_assign()
        self.assertEqual(
            sum(backorder.move_ids.move_line_ids.mapped("quantity_product_uom")), 8
        )

    def test_return_all_counts_the_returns_still_open(self):
        product = self._product("ret-open")
        receipt = self.env["stock.picking"].create(
            {
                "picking_type_id": self.wh.in_type_id.id,
                "location_id": self.supplier.id,
                "location_dest_id": self.stock.id,
                "move_ids": [
                    Command.create(
                        {
                            "product_id": product.id,
                            "product_uom_qty": 10,
                            "location_id": self.supplier.id,
                            "location_dest_id": self.stock.id,
                        },
                    ),
                ],
            },
        )
        receipt.action_confirm()
        receipt.move_ids.quantity = 10
        receipt.move_ids.picked = True
        receipt._action_done()
        consumed = self.Move.create(
            {
                "product_id": product.id,
                "product_uom_qty": 10,
                "location_id": self.stock.id,
                "location_dest_id": self.customer.id,
            },
        )
        consumed._action_confirm()
        consumed._action_assign()
        consumed.picked = True
        consumed._action_done()

        Wizard = self.env["stock.return.picking"].with_context(
            active_id=receipt.id, active_model="stock.picking"
        )
        first = Wizard.create({})
        first.product_return_moves.quantity = 4
        open_return = first._create_return()
        self.assertEqual(open_return.move_ids.quantity, 0, "nothing to reserve")

        action = Wizard.create({}).action_create_returns_all()

        second = self.env["stock.picking"].browse(action["res_id"])
        self.assertEqual(second.move_ids.product_uom_qty, 6)

    def test_lowering_demand_on_a_picked_move_recomputes_its_state(self):
        product = self._product("dem-picked", 10)
        move = self._delivery(product, qty=12).move_ids
        self.assertEqual(move.state, "partially_available")
        move.picked = True

        move.product_uom_qty = 5

        self.assertEqual(move.quantity, 10)
        self.assertEqual(move.state, "assigned")

    def test_validating_an_empty_picked_move_without_backorder(self):
        product, other = self._product("empty-a", 10), self._product("empty-b", 10)
        picking = self._delivery(product | other)
        move, other_move = picking.move_ids
        move.move_line_ids.quantity = 0
        self.env["stock.move.line"].create(
            {
                "move_id": move.id,
                "product_id": product.id,
                "location_id": self.stock.id,
                "location_dest_id": self.customer.id,
                "picking_id": picking.id,
                "quantity": 0,
                "picked": True,
            },
        )
        other_move.picked = True
        self.assertTrue(move.picked)

        picking.move_ids._action_done(cancel_backorder=True)

        self.assertEqual(move.state, "cancel")
        self.assertFalse(move.move_line_ids)
        self.assertEqual(other_move.state, "done")

    def test_lot_split_settles_float_remainders(self):
        split = self.Move._prepare_lot_generation_split
        self.assertEqual(split(6, 0.6), [0.6] * 10)
        self.assertEqual(split(1, 0.1), [0.1] * 10)
        self.assertEqual(split(0.05, 0.01), [0.01] * 5)
        self.assertEqual(split(1, 0.3), [0.3, 0.3, 0.3, 0.1])
        self.assertEqual(split(5, 2), [2, 2, 1])

        product = self._product("lot-split", tracking="lot")
        vals = self.Move.action_generate_lot_line_vals(
            {
                "default_product_id": product.id,
                "default_tracking": "lot",
                "default_location_dest_id": self.stock.id,
                "default_quantity": 6,
                "default_picking_type_id": self.wh.in_type_id.id,
                "default_company_id": self.env.company.id,
            },
            "generate",
            "LOT0001",
            0.6,
            "",
        )
        self.assertEqual(len(vals), 10)
        self.assertEqual(vals[-1]["lot_name"], "LOT0010")

    def test_unlinking_a_linked_move_while_uninstalling(self):
        product = self._product("unl-linked")
        upstream, downstream = self.Move.create(
            [
                {
                    "product_id": product.id,
                    "product_uom_qty": 1,
                    "location_id": self.stock.id,
                    "location_dest_id": self.output.id,
                },
                {
                    "product_id": product.id,
                    "product_uom_qty": 1,
                    "location_id": self.output.id,
                    "location_dest_id": self.customer.id,
                },
            ],
        )
        downstream.move_orig_ids = [Command.link(upstream.id)]
        (upstream | downstream)._action_confirm(merge=False)

        with self.assertRaises(UserError), self.env.cr.savepoint():
            upstream.unlink()
        upstream.with_context(**{MODULE_UNINSTALL_FLAG: True}).unlink()

        self.assertFalse(upstream.exists())

    def _validate_with_backorders(self, count):
        products = self.env["product.product"].create(
            [
                {"name": f"bo-note-{count}-{i}", "is_storable": True}
                for i in range(count)
            ],
        )
        for product in products:
            self.env["stock.quant"]._update_available_quantity(product, self.stock, 5)
        picking = self._delivery(products)
        for move in picking.move_ids:
            move.quantity = 3
        picking.move_ids.picked = True
        notes_before = set(picking.message_ids.ids)
        statements = self._statements(picking._action_done)
        notes = picking.message_ids.filtered(lambda m: m.id not in notes_before)
        return statements, notes

    def test_a_backorder_split_is_not_a_demand_edit(self):
        few, notes = self._validate_with_backorders(4)
        self.assertFalse(
            [n for n in notes if "initial demand has been updated" in (n.body or "")],
            "splitting the remainder into a backorder is not an edit of the demand",
        )
        many, _notes = self._validate_with_backorders(12)
        self.assertLessEqual(
            (many - few) / 8,
            2,
            f"validation with backorders costs {few} statements for 4 lines and "
            f"{many} for 12",
        )

    def _cancel_chain(self, count):
        products = self.env["product.product"].create(
            [{"name": f"cc-{count}-{i}", "is_storable": True} for i in range(count)],
        )
        for product in products:
            self.env["stock.quant"]._update_available_quantity(product, self.stock, 10)
        pick = self.env["stock.picking"].create(
            {
                "picking_type_id": self.wh.int_type_id.id,
                "location_id": self.stock.id,
                "location_dest_id": self.output.id,
                "move_ids": [
                    Command.create(
                        {
                            "product_id": product.id,
                            "product_uom_qty": 5,
                            "location_id": self.stock.id,
                            "location_dest_id": self.output.id,
                        },
                    )
                    for product in products
                ],
            },
        )
        ship = self.env["stock.picking"].create(
            {
                "picking_type_id": self.wh.out_type_id.id,
                "location_id": self.output.id,
                "location_dest_id": self.customer.id,
                "move_ids": [
                    Command.create(
                        {
                            "product_id": product.id,
                            "product_uom_qty": 5,
                            "location_id": self.output.id,
                            "location_dest_id": self.customer.id,
                        },
                    )
                    for product in products
                ],
            },
        )
        for upstream, downstream in zip(pick.move_ids, ship.move_ids, strict=True):
            downstream.move_orig_ids = [Command.link(upstream.id)]
        (pick | ship).action_confirm()
        pick.action_assign()
        statements = self._statements(pick.action_cancel)
        self.assertEqual(set(ship.move_ids.mapped("state")), {"cancel"})
        return statements

    def test_cancel_cascades_in_one_call(self):
        few = self._cancel_chain(4)
        many = self._cancel_chain(12)
        self.assertLessEqual(
            (many - few) / 8,
            1.5,
            f"cancelling a chain costs {few} statements for 4 moves and {many} for 12",
        )

    def test_merged_move_state_is_left_to_recompute(self):
        product = self._product("merge-state", 100)
        picking = self._delivery(product)
        extra = self.Move.create(
            {
                "product_id": product.id,
                "product_uom_qty": 5,
                "location_id": self.stock.id,
                "location_dest_id": self.customer.id,
                "picking_id": picking.id,
            },
        )
        extra._action_confirm(merge=False)
        extra._action_assign()
        self.assertNotIn("state", picking.move_ids._prepare_merge_moves_vals())

        kept = picking.move_ids._merge_moves()

        self.assertEqual(len(kept.exists()), 1)
        self.assertEqual(kept.exists().state, "assigned")
        self.assertEqual(kept.exists().quantity, 10)

    def test_the_server_side_serial_generator_is_gone(self):
        self.assertNotIn("next_serial", self.Move._fields)
        self.assertNotIn("next_serial_count", self.Move._fields)
        self.assertFalse(hasattr(self.Move, "_update_move_lines_for_serials"))
        self.assertFalse(hasattr(self.Move, "_prepare_serial_move_line_commands"))

    def test_a_later_group_joins_a_picking_created_by_the_same_call(self):
        product = self._product("join-created", 100)
        r1, r2, r3 = self.env["stock.reference"].create(
            [{"name": "JOIN-R1"}, {"name": "JOIN-R2"}, {"name": "JOIN-R3"}],
        )
        moves = self.Move.create(
            [
                {
                    "product_id": product.id,
                    "product_uom_qty": 1,
                    "location_id": self.stock.id,
                    "location_dest_id": self.customer.id,
                    "picking_type_id": self.wh.out_type_id.id,
                    "reference_ids": [Command.set(refs.ids)],
                }
                for refs in (r1, r1 | r2, r1 | r3)
            ],
        )

        moves._action_confirm(merge=False)

        self.assertEqual(
            len(moves.picking_id),
            1,
            "a picking whose references the group covers is joined once it is "
            "created, whether by this call or an earlier one",
        )

    def test_push_rule_cache_is_per_product(self):
        inter = self.env["stock.location"].create(
            {"name": "push-in", "location_id": self.stock.id, "usage": "internal"},
        )
        target = self.env["stock.location"].create(
            {"name": "push-out", "location_id": self.stock.id, "usage": "internal"},
        )
        route = self.env["stock.route"].create(
            {
                "name": "per-product push",
                "warehouse_selectable": True,
                "warehouse_ids": [Command.link(self.wh.id)],
                "rule_ids": [
                    Command.create(
                        {
                            "name": "push-in to push-out",
                            "action": "push",
                            "location_src_id": inter.id,
                            "location_dest_id": target.id,
                            "picking_type_id": self.wh.int_type_id.id,
                            "warehouse_id": self.wh.id,
                        },
                    ),
                ],
            },
        )
        usable, unusable = self._product("push-a"), self._product("push-b")
        moves = self.Move.create(
            [
                {
                    "product_id": product.id,
                    "product_uom_qty": 1,
                    "location_id": self.supplier.id,
                    "location_dest_id": inter.id,
                    "warehouse_id": self.wh.id,
                }
                for product in (usable, unusable)
            ],
        )
        StockRule = type(self.env["stock.rule"])
        original = StockRule._is_route_usable_for

        def usable_for(rule_model, product, candidate):
            if candidate == route and product == unusable:
                return False
            return original(rule_model, product, candidate)

        with patch.object(StockRule, "_is_route_usable_for", usable_for):
            moves._push_apply()

        self.assertTrue(moves[0].move_dest_ids, "sanity: the usable product pushes")
        self.assertFalse(
            moves[1].move_dest_ids,
            "the rule found for one product was reused for another the route "
            "is not usable for",
        )

    def test_overlapping_candidate_sets_merge_a_move_once(self):
        product, other = self._product("overlap", 100), self._product("overlap-b", 100)
        picking = self._delivery(product | other)
        extra = self.Move.create(
            {
                "product_id": product.id,
                "product_uom_qty": 1,
                "location_id": self.stock.id,
                "location_dest_id": self.customer.id,
                "picking_id": picking.id,
            },
        )
        outsider = self.Move.create(
            {
                "product_id": other.id,
                "product_uom_qty": 1,
                "location_id": self.stock.id,
                "location_dest_id": self.customer.id,
            },
        )
        StockMove = type(self.Move)
        original = StockMove._update_candidate_moves_list

        def overlapping(moves, candidate_moves_set):
            original(moves, candidate_moves_set)
            candidate_moves_set.add(
                picking.move_ids.filtered(lambda m: m.product_id == product) | outsider
            )

        with patch.object(StockMove, "_update_candidate_moves_list", overlapping):
            extra._action_confirm()

        merged = picking.move_ids.filtered(lambda m: m.product_id == product)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged.product_uom_qty, 6)

    def test_merge_keys_only_the_moves_of_the_merged_products(self):
        products = self.env["product.product"].create(
            [{"name": f"mk-{i}", "is_storable": True} for i in range(20)],
        )
        picking = self._delivery(products)
        newcomer = self._product("mk-new")
        extra = self.Move.create(
            {
                "product_id": newcomer.id,
                "product_uom_qty": 1,
                "location_id": self.stock.id,
                "location_dest_id": self.customer.id,
                "picking_id": picking.id,
            },
        )
        keyed = []
        StockMove = type(self.Move)
        original = StockMove._get_merge_key

        def counting_key(moves, distinct_fields, excluded_fields=None):
            key = original(moves, distinct_fields, excluded_fields)

            def counted(move):
                keyed.append(move.id)
                return key(move)

            return counted

        with patch.object(StockMove, "_get_merge_key", counting_key):
            extra._action_confirm()

        self.assertLessEqual(len(set(keyed)), 1, f"keyed {len(set(keyed))} moves")

    def test_done_moves_do_not_carry_the_completion_flag(self):
        product = self._product("flag", 10)
        pick = self.Move.create(
            {
                "product_id": product.id,
                "product_uom_qty": 2,
                "location_id": self.stock.id,
                "location_dest_id": self.output.id,
                "picking_type_id": self.wh.int_type_id.id,
            },
        )
        ship = self.Move.create(
            {
                "product_id": product.id,
                "product_uom_qty": 2,
                "location_id": self.output.id,
                "location_dest_id": self.customer.id,
                "picking_type_id": self.wh.out_type_id.id,
                "move_orig_ids": [Command.link(pick.id)],
            },
        )
        (pick | ship)._action_confirm(merge=False)
        pick._action_assign()
        pick.picked = True
        assigned_under_flag = []
        StockMove = type(self.Move)
        original = StockMove._action_assign

        def recording(moves, *args, **kwargs):
            if ship in moves:
                assigned_under_flag.append(
                    is_internal_flag(moves.env.context, CONTEXT_BLOCK_COMPLETING),
                )
            return original(moves, *args, **kwargs)

        with patch.object(StockMove, "_action_assign", recording):
            done = pick._action_done()

        self.assertEqual(ship.state, "assigned")
        self.assertEqual(assigned_under_flag, [False])
        self.assertFalse(is_internal_flag(done.env.context, CONTEXT_BLOCK_COMPLETING))

    def test_mtso_remainder_is_procured_in_a_unit_that_holds_it(self):
        product = self._product("mtso-dozen", 5, uom_ids=[(4, self.dozen.id)])
        route = self.env["stock.route"].create(
            {
                "name": "mtso dozen",
                "product_selectable": True,
                "rule_ids": [
                    Command.create(
                        {
                            "name": "stock to customers, else procure",
                            "action": "pull",
                            "procure_method": "mts_else_mto",
                            "location_src_id": self.stock.id,
                            "location_dest_id": self.customer.id,
                            "picking_type_id": self.wh.out_type_id.id,
                        },
                    ),
                    Command.create(
                        {
                            "name": "vendors to stock",
                            "action": "pull",
                            "procure_method": "make_to_stock",
                            "location_src_id": self.supplier.id,
                            "location_dest_id": self.stock.id,
                            "picking_type_id": self.wh.in_type_id.id,
                        },
                    ),
                ],
            },
        )
        product.route_ids = [Command.set(route.ids)]
        mtso_rule = route.rule_ids.filtered(
            lambda r: r.procure_method != "make_to_stock"
        )
        move = self.Move.create(
            {
                "product_id": product.id,
                "product_uom_id": self.dozen.id,
                "product_uom_qty": 1,
                "location_id": self.stock.id,
                "location_dest_id": self.customer.id,
                "picking_type_id": self.wh.out_type_id.id,
                "rule_id": mtso_rule.id,
                "warehouse_id": self.wh.id,
            },
        )

        move._action_confirm()

        supply = self.Move.search(
            [("product_id", "=", product.id), ("location_id", "=", self.supplier.id)],
        )
        self.assertEqual(
            supply.product_qty,
            7,
            "12 units wanted, 5 free: 7 are procured, not 0.58 dozen (6.96)",
        )

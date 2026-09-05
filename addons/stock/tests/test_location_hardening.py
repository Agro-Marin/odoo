from collections import Counter
from contextlib import contextmanager

from odoo.exceptions import UserError
from odoo.fields import Domain
from odoo.tests.common import TransactionCase, tagged

from ..models.stock_location_putaway import PutawayScan


class LocationHardeningCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Location = cls.env["stock.location"]
        cls.Quant = cls.env["stock.quant"]
        cls.stock_location = cls.env.ref("stock.stock_location_stock")
        cls.group_hard_override = cls.env.ref("stock.group_override_hard_block")

    @classmethod
    def _create_product(cls, name, weight=1.0, **vals):
        return cls.env["product.product"].create(
            {"name": name, "is_storable": True, "weight": weight, **vals},
        )

    @classmethod
    def _create_location(cls, name, parent=None, **vals):
        return cls.Location.create(
            {
                "name": name,
                "location_id": (parent or cls.stock_location).id,
                "usage": "internal",
                **vals,
            },
        )

    def _create_user(self, login, *groups):
        return self.env["res.users"].create(
            {
                "name": login,
                "login": login,
                "group_ids": [
                    (
                        6,
                        0,
                        [
                            self.env.ref("base.group_user").id,
                            self.env.ref("stock.group_stock_manager").id,
                            *[group.id for group in groups],
                        ],
                    ),
                ],
            },
        )


@tagged("post_install", "-at_install")
class TestPutawayBatchHonoursItsOwnPlacements(LocationHardeningCase):
    def _create_putaway_scenario(self, name, category_vals=None, capacity_qty=None):
        category = self.env["stock.storage.category"].create(
            {"name": name, **(category_vals or {})},
        )
        view = self._create_location(f"{name} View", usage="view")
        shelves = self.Location.create(
            [
                {
                    "name": f"{name}{letter}",
                    "location_id": view.id,
                    "usage": "internal",
                    "storage_category_id": category.id,
                }
                for letter in "AB"
            ],
        )
        product = self._create_product(f"{name} Product")
        self.env["stock.putaway.rule"].create(
            {
                "location_in_id": view.id,
                "location_out_id": view.id,
                "product_id": product.id,
                "storage_category_id": category.id,
            },
        )
        if capacity_qty is not None:
            self.env["stock.storage.category.capacity"].create(
                {
                    "storage_category_id": category.id,
                    "product_id": product.id,
                    "quantity": capacity_qty,
                },
            )
        self.env.flush_all()
        return view, shelves, product

    def _placed(self, view, product, quantities):
        locations = view._get_putaway_strategy_batch(product, quantities)
        placed = {}
        for quantity, location in zip(quantities, locations, strict=True):
            placed[location] = placed.get(location, 0.0) + quantity
        return placed

    def test_a_batch_does_not_pile_past_the_weight_capacity(self):
        view, __, product = self._create_putaway_scenario(
            "Weight", {"max_weight": 10.0}
        )
        placed = self._placed(view, product, [4.0] * 4)
        self.assertTrue(
            all(quantity * product.weight <= 10.0 for quantity in placed.values()),
            "16 kg of a 10 kg-capped category was placed as "
            f"{ {location.name: qty for location, qty in placed.items()} }",
        )

    def test_it_spills_to_the_second_shelf_exactly_as_the_quantity_cap_does(self):
        weight_view, __, weight_product = self._create_putaway_scenario(
            "W2", {"max_weight": 10.0}
        )
        qty_view, __, qty_product = self._create_putaway_scenario(
            "Q2", capacity_qty=10.0
        )
        by_weight = sorted(
            self._placed(weight_view, weight_product, [4.0] * 4).values()
        )
        by_quantity = sorted(self._placed(qty_view, qty_product, [4.0] * 4).values())
        self.assertEqual(by_weight, by_quantity)
        self.assertEqual(by_weight, [8.0, 8.0])

    def test_committed_stock_still_decides_a_single_placement(self):
        view, shelves, product = self._create_putaway_scenario(
            "W3", {"max_weight": 10.0}
        )
        self.Quant._update_available_quantity(product, shelves[0], 8)
        self.env.flush_all()
        self.assertEqual(view._get_putaway_strategy(product, 4.0), shelves[1])

    @contextmanager
    def _counting_queries(self):
        cursor_class = type(self.env.cr)
        original = cursor_class.execute
        counter = Counter()

        def patched(cursor, query, params=None, log_exceptions=True):
            counter["queries"] += 1
            return original(cursor, query, params, log_exceptions)

        cursor_class.execute = patched
        try:
            yield counter
        finally:
            cursor_class.execute = original

    def test_the_batch_does_not_cost_more_the_longer_it_gets(self):
        view, __, product = self._create_putaway_scenario("W4", {"max_weight": 1000.0})
        view._get_putaway_strategy_batch(product, [1.0])
        counts = {}
        for length in (1, 5, 20):
            self.env.flush_all()
            self.env.invalidate_all()
            with self._counting_queries() as counter:
                view._get_putaway_strategy_batch(product, [1.0] * length)
            counts[length] = counter["queries"]
        self.assertEqual(
            sorted(set(counts.values())),
            [counts[20]],
            f"a putaway batch still scales with its length: {counts}. Nothing is "
            "written between placements, so every aggregate a longer batch adds "
            "is byte-identical to one it already ran.",
        )

    def test_a_caller_supplied_additional_qty_is_not_counted_as_weight(self):
        product = self._create_product("Seeded", weight=2.0)
        scan = PutawayScan(product, {7: 100.0})
        self.assertEqual(scan.placed[7], 100.0)
        self.assertEqual(scan.staged_weight(7), 0.0)
        scan.place(self.stock_location.browse(7), 3.0)
        self.assertEqual(scan.placed[7], 103.0)
        self.assertEqual(scan.staged_weight(7), 6.0)


@tagged("post_install", "-at_install")
class TestArchivingCannotBeWaivedFromTheContext(LocationHardeningCase):
    def setUp(self):
        super().setUp()
        self.product = self._create_product("Archive Product")
        self.parent = self._create_location("Archive Parent")
        self.child = self._create_location("Archive Child", parent=self.parent)
        self.grandchild = self._create_location("Archive Grandchild", parent=self.child)

    def test_a_forged_context_key_no_longer_waives_the_stock_check(self):
        self.Quant._update_available_quantity(self.product, self.parent, 6)
        self.env.flush_all()
        with self.assertRaises(UserError):
            self.parent.write({"active": False})
        with self.assertRaises(UserError):
            self.parent.with_context(do_not_check_quant=True).write({"active": False})
        with self.assertRaises(UserError):
            self.parent.with_context(stock_location_active_cascade=True).write(
                {"active": False},
            )
        self.assertTrue(self.parent.active)

    def test_archiving_still_cascades_to_the_whole_subtree(self):
        self.parent.write({"active": False})
        self.env.flush_all()
        for location in (self.parent, self.child, self.grandchild):
            self.assertFalse(location.active, f"{location.name} stayed active")

    def test_unarchiving_still_cascades_to_the_whole_subtree(self):
        self.parent.write({"active": False})
        self.parent.write({"active": True})
        self.env.flush_all()
        for location in (self.parent, self.child, self.grandchild):
            self.assertTrue(location.active, f"{location.name} stayed archived")

    def test_a_transit_location_holding_stock_refuses_to_archive(self):
        transit = self._create_location("Transit Box", usage="transit")
        self.Quant._update_available_quantity(self.product, transit, 12)
        self.env.flush_all()
        self.env.invalidate_all()
        self.assertFalse(transit.is_empty)
        with self.assertRaises(UserError):
            transit.write({"active": False})

    def test_the_refusal_names_each_location_once(self):
        other = self._create_product("Second Archive Product")
        self.Quant._update_available_quantity(self.product, self.child, 3)
        self.Quant._update_available_quantity(other, self.child, 4)
        self.env.flush_all()
        with self.assertRaises(UserError) as caught:
            self.parent.write({"active": False})
        self.assertEqual(str(caught.exception).count(self.child.display_name), 1)


@tagged("post_install", "-at_install")
class TestDeletingIsGovernedLikeArchiving(LocationHardeningCase):
    def setUp(self):
        super().setUp()
        self.blocked = self._create_location("Hard Blocked Leaf")
        self.blocked.block_type = "hard"
        self.env.flush_all()
        self.manager = self._create_user("hardening_manager")
        self.unlocker = self._create_user(
            "hardening_unlocker", self.group_hard_override
        )

    def test_a_manager_who_cannot_archive_it_cannot_delete_it_either(self):
        self.assertFalse(self.manager.has_group("stock.group_override_hard_block"))
        with self.assertRaises(UserError):
            self.blocked.with_user(self.manager).write({"active": False})
        with self.assertRaises(UserError):
            self.blocked.with_user(self.manager).unlink()
        self.assertTrue(self.blocked.exists())

    def test_the_unlock_group_may_still_delete_it(self):
        self.blocked.with_user(self.unlocker).unlink()
        self.assertFalse(self.blocked.exists())

    def test_the_block_is_read_over_the_whole_subtree_not_just_the_receiver(self):
        parent = self._create_location("Governed Parent")
        child = self._create_location("Governed Child", parent=parent)
        child.block_type = "hard"
        self.env.flush_all()
        with self.assertRaises(UserError):
            parent.with_context(stock_unlink_subtree=True).with_user(
                self.manager,
            ).unlink()

    def test_an_unblocked_location_still_deletes(self):
        plain = self._create_location("Plain Leaf")
        plain.with_user(self.manager).unlink()
        self.assertFalse(plain.exists())


@tagged("post_install", "-at_install")
class TestIsEmptyTracksItsQuants(LocationHardeningCase):
    def test_adding_stock_makes_a_location_stop_reporting_empty(self):
        product = self._create_product("Empty Product")
        shelf = self._create_location("Empty Shelf")
        self.assertTrue(shelf.is_empty)
        self.Quant._update_available_quantity(product, shelf, 7)
        self.env.flush_all()
        self.assertFalse(
            shelf.is_empty,
            "is_empty answered from a cache no quant write invalidates",
        )

    def test_removing_the_stock_makes_it_report_empty_again(self):
        product = self._create_product("Empty Product 2")
        shelf = self._create_location("Empty Shelf 2")
        self.Quant._update_available_quantity(product, shelf, 7)
        self.env.flush_all()
        self.assertFalse(shelf.is_empty)
        self.Quant._update_available_quantity(product, shelf, -7)
        self.env.flush_all()
        self.assertTrue(shelf.is_empty)

    def test_the_search_and_the_field_agree_in_both_directions(self):
        product = self._create_product("Search Product")
        full = self._create_location("Search Full")
        empty = self._create_location("Search Empty")
        self.Quant._update_available_quantity(product, full, 2)
        self.env.flush_all()
        occupied = self.Location.search([("is_empty", "=", False)])
        vacant = self.Location.search([("is_empty", "=", True)])
        self.assertIn(full, occupied)
        self.assertNotIn(empty, occupied)
        self.assertIn(empty, vacant)
        self.assertNotIn(full, vacant)


@tagged("post_install", "-at_install")
class TestTheDestinationDomainIsBuiltOnce(LocationHardeningCase):
    def test_the_outbound_half_is_the_negation_of_the_inbound_one(self):
        Move = self.env["stock.move"]
        ids = self.stock_location.ids
        into, out_of = self.Location._get_domains_move_destination(
            lambda field: Domain(field, "child_of", ids),
        )
        self.assertEqual(
            set(Move.search(out_of).ids),
            set(Move.search(~into).ids),
        )

    def test_skipping_in_progress_drops_the_final_location(self):
        ids = self.stock_location.ids
        plain, __ = self.Location._get_domains_move_destination(
            lambda field: Domain(field, "child_of", ids),
        )
        skipping, __ = self.Location.with_context(
            skip_in_progress=True,
        )._get_domains_move_destination(lambda field: Domain(field, "child_of", ids))
        self.assertIn("location_final_id", repr(plain))
        self.assertNotIn("location_final_id", repr(skipping))

    def test_the_strict_scope_never_grows_a_final_location_clause(self):
        strict = self.Location.with_context(strict=True)._get_domains_quantity(
            self.stock_location.ids,
        )
        self.assertNotIn("location_final_id", repr(strict))

    def test_an_empty_scope_is_false_in_all_three_domains(self):
        self.assertEqual(
            [repr(domain) for domain in self.Location._get_domains_quantity(set())],
            [repr(Domain.FALSE)] * 3,
        )


@tagged("post_install", "-at_install")
class TestTheReservedBreakdownIsKeyedByUnit(LocationHardeningCase):
    def test_two_units_sharing_a_name_stay_separate(self):
        reference = self.env["uom.uom"].search([], limit=1)
        twin = self.env["uom.uom"].create(
            {
                "name": reference.name,
                "relative_factor": 1.0,
                "relative_uom_id": reference.id,
            },
        )
        self.assertEqual(twin.name, reference.name)
        self.assertNotEqual(twin, reference)
        breakdown = {reference: 2.0, twin: 3.0}
        self.assertEqual(len(breakdown), 2)
        rendered = self.Location._format_reserved_quantities(breakdown)
        self.assertEqual(rendered.count(reference.name), 2)

    def test_a_location_with_no_reservation_renders_nothing(self):
        self.assertEqual(self.Location._format_reserved_quantities({}), "")


@tagged("post_install", "-at_install")
class TestUsageConversionAsksOnce(LocationHardeningCase):
    def test_a_view_refuses_even_an_emptied_quant(self):
        product = self._create_product("Convert Product")
        shelf = self._create_location("Convert Shelf")
        self.Quant._update_available_quantity(product, shelf, 5)
        self.Quant._update_available_quantity(product, shelf, -5)
        self.env.flush_all()
        self.assertTrue(
            self.Quant.search([("location_id", "=", shelf.id)]),
            "the emptied quant row is what this test is about",
        )
        with self.assertRaises(UserError):
            shelf.write({"usage": "view"})

    def test_a_transit_conversion_accepts_the_same_emptied_quant(self):
        product = self._create_product("Convert Product 2")
        shelf = self._create_location("Convert Shelf 2")
        self.Quant._update_available_quantity(product, shelf, 5)
        self.Quant._update_available_quantity(product, shelf, -5)
        self.env.flush_all()
        shelf.write({"usage": "transit"})
        self.assertEqual(shelf.usage, "transit")

    def test_stock_still_refuses_any_conversion(self):
        product = self._create_product("Convert Product 3")
        shelf = self._create_location("Convert Shelf 3")
        self.Quant._update_available_quantity(product, shelf, 5)
        self.env.flush_all()
        with self.assertRaises(UserError):
            shelf.write({"usage": "transit"})


@tagged("post_install", "-at_install")
class TestTheBlockSurvivesAQuantIdWrite(LocationHardeningCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env["stock.warehouse"].search([], limit=1)
        cls.customer_location = cls.env.ref("stock.stock_location_customers")
        cls.blocked_product = cls._create_product("Quant Bypass Product")
        cls.free_location = cls._create_location("Bypass Free")
        cls.blocked_location = cls._create_location(
            "Bypass Blocked",
            block_type="soft_out",
        )
        cls.env["stock.quant"].create(
            [
                {
                    "product_id": cls.blocked_product.id,
                    "location_id": cls.free_location.id,
                    "quantity": 50,
                },
                {
                    "product_id": cls.blocked_product.id,
                    "location_id": cls.blocked_location.id,
                    "quantity": 50,
                },
            ],
        )
        cls.blocked_quant = cls.env["stock.quant"].search(
            [
                ("location_id", "=", cls.blocked_location.id),
                ("product_id", "=", cls.blocked_product.id),
            ],
        )
        cls.stock_user = cls.env["res.users"].create(
            {
                "name": "Hardening Stock User",
                "login": "hardening_block_stock_user",
                "group_ids": [
                    (
                        6,
                        0,
                        [
                            cls.env.ref("base.group_user").id,
                            cls.env.ref("stock.group_stock_user").id,
                            cls.env.ref("stock.group_stock_multi_locations").id,
                        ],
                    ),
                ],
            },
        )
        cls.env.flush_all()

    def test_the_fixture_is_not_a_superuser(self):
        self.assertFalse(self._reserved_line().env.su)
        self.assertEqual(
            self.blocked_location.effective_block_type,
            "soft_out",
        )

    def _reserved_line(self):
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.warehouse.out_type_id.id,
                "location_id": self.free_location.id,
                "location_dest_id": self.customer_location.id,
            },
        )
        move = self.env["stock.move"].create(
            {
                "picking_id": picking.id,
                "product_id": self.blocked_product.id,
                "product_uom_qty": 5,
                "location_id": self.free_location.id,
                "location_dest_id": self.customer_location.id,
            },
        )
        picking.action_confirm()
        picking.action_assign()
        self.assertTrue(
            move.move_line_ids,
            "nothing reserved, so there is no line to redirect and the tests "
            "below would pass for the wrong reason",
        )
        return move.move_line_ids[0].with_user(self.stock_user)

    def test_naming_the_blocked_location_outright_is_refused(self):
        with self.assertRaises(UserError):
            self._reserved_line().write({"location_id": self.blocked_location.id})

    def test_naming_a_quant_that_lives_there_is_refused_too(self):
        with self.assertRaises(UserError):
            self._reserved_line().write({"quant_id": self.blocked_quant.id})

    def test_the_same_holds_through_web_save(self):
        with self.assertRaises(UserError):
            self._reserved_line().web_save(
                {"quant_id": self.blocked_quant.id},
                {"id": {}, "location_id": {}},
            )

    def test_creating_a_line_on_a_blocked_quant_is_still_refused(self):
        line = self._reserved_line()
        with self.assertRaises(UserError):
            self.env["stock.move.line"].with_user(self.stock_user).create(
                {
                    "move_id": line.move_id.id,
                    "product_id": self.blocked_product.id,
                    "product_uom_id": self.blocked_product.uom_id.id,
                    "quantity": 1,
                    "quant_id": self.blocked_quant.id,
                    "location_dest_id": self.customer_location.id,
                },
            )

    def test_an_unblocked_quant_is_still_reachable_by_quant_id(self):
        free_quant = self.env["stock.quant"].search(
            [
                ("location_id", "=", self.free_location.id),
                ("product_id", "=", self.blocked_product.id),
            ],
        )
        line = self._reserved_line()
        line.write({"quant_id": free_quant.id})
        self.assertEqual(line.location_id, self.free_location)


@tagged("post_install", "-at_install")
class TestTheProductGuardReadsTheStoredState(LocationHardeningCase):
    def setUp(self):
        super().setUp()
        self.plain_user = self.env["res.users"].create(
            {
                "name": "Plain Stock User",
                "login": "hardening_plain_stock_user",
                "group_ids": [
                    (
                        6,
                        0,
                        [
                            self.env.ref("base.group_user").id,
                            self.env.ref("stock.group_stock_user").id,
                            self.env.ref("stock.group_stock_multi_locations").id,
                        ],
                    ),
                ],
            },
        )
        self.first = self._create_product("Guard Product One")
        self.second = self._create_product("Guard Product Two")

    def _moveless_line(self):
        line = (
            self.env["stock.move.line"]
            .with_user(self.plain_user)
            .create(
                {
                    "product_id": self.first.id,
                    "product_uom_id": self.first.uom_id.id,
                    "quantity": 1,
                    "location_id": self.stock_location.id,
                    "location_dest_id": self.stock_location.id,
                    "company_id": self.env.company.id,
                },
            )
        )
        self.env.flush_all()
        self.assertFalse(line.move_id, "the exposure is move-less lines only")
        self.assertFalse(line.state, "a move-less line has no stored state")
        return line

    def test_changing_the_product_is_refused(self):
        with self.assertRaises(UserError):
            self._moveless_line().write({"product_id": self.second.id})

    def test_supplying_a_draft_state_does_not_lift_the_refusal(self):
        with self.assertRaises(UserError):
            self._moveless_line().write(
                {"product_id": self.second.id, "state": "draft"},
            )

    def test_a_move_bound_line_is_refused_with_or_without_a_supplied_state(self):
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.env.ref("stock.picking_type_in").id,
                "location_id": self.env.ref("stock.stock_location_suppliers").id,
                "location_dest_id": self.stock_location.id,
            },
        )
        move = self.env["stock.move"].create(
            {
                "picking_id": picking.id,
                "product_id": self.first.id,
                "product_uom_qty": 1,
                "location_id": self.env.ref("stock.stock_location_suppliers").id,
                "location_dest_id": self.stock_location.id,
            },
        )
        picking.action_confirm()
        line = self.env["stock.move.line"].create(
            {
                "move_id": move.id,
                "product_id": self.first.id,
                "product_uom_id": self.first.uom_id.id,
                "quantity": 1,
                "location_dest_id": self.stock_location.id,
            },
        )
        for vals in (
            {"product_id": self.second.id},
            {"product_id": self.second.id, "state": "draft"},
        ):
            with self.assertRaises(UserError):
                line.write(vals)

    def test_writing_the_same_product_is_still_allowed(self):
        line = self._moveless_line()
        line.write({"product_id": self.first.id, "quantity": 2})
        self.assertEqual(line.quantity, 2)

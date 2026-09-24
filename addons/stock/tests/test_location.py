from psycopg.errors import CheckViolation, UniqueViolation

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.stock.tests.common import LocationCase, TestStockCommon


@tagged("post_install", "-at_install")
class TestStockLocationEmptiness(TestStockCommon):
    def _create_quant(self, location, quantity=0.0, reserved_quantity=0.0):
        return self.env["stock.quant"].create(
            {
                "product_id": self.productA.id,
                "location_id": location.id,
                "quantity": quantity,
                "reserved_quantity": reserved_quantity,
            },
        )

    def _search_is_empty(self, location):
        return location in self.env["stock.location"].search([("is_empty", "=", True)])

    def assertOccupied(self, location, because):
        location.invalidate_recordset(["is_empty"])
        self.assertFalse(location.is_empty, f"is_empty should be False: {because}")
        self.assertFalse(
            self._search_is_empty(location),
            f"the is_empty search disagrees with the compute: {because}",
        )
        with self.assertRaises(UserError, msg=f"should not archive: {because}"):
            location.action_archive()

    def test_negative_stock_is_not_empty(self):
        self._create_quant(self.shelf_1, quantity=-5)
        self.assertOccupied(self.shelf_1, "the location holds a negative quant")

    def test_reserved_only_location_is_not_empty(self):
        self._create_quant(self.shelf_1, quantity=0, reserved_quantity=3)
        self.assertOccupied(self.shelf_1, "the location holds a reservation")

    def test_opposite_quantities_do_not_cancel_out(self):
        self._create_quant(self.shelf_1, quantity=5)
        self.env["stock.quant"].create(
            {
                "product_id": self.productB.id,
                "location_id": self.shelf_1.id,
                "quantity": -5,
            },
        )
        self.assertOccupied(self.shelf_1, "two products net to zero but both exist")

    def test_truly_empty_location_is_empty_and_archives(self):
        self.shelf_1.invalidate_recordset(["is_empty"])
        self.assertTrue(self.shelf_1.is_empty)
        self.assertTrue(self._search_is_empty(self.shelf_1))
        self.shelf_1.action_archive()
        self.assertFalse(self.shelf_1.active)

    def test_is_empty_search_partitions_the_set(self):
        self._create_quant(self.shelf_1, quantity=5)
        Location = self.env["stock.location"]
        empty = Location.search([("is_empty", "=", True)])
        occupied = Location.search([("is_empty", "=", False)])
        self.assertFalse(empty & occupied)
        self.assertEqual(len(empty | occupied), Location.search_count([]))
        self.assertIn(self.shelf_1, occupied)


@tagged("post_install", "-at_install")
class TestStockLocationTree(TestStockCommon):
    def _assert_warehouse(self, locations, warehouse):
        locations.invalidate_recordset(["warehouse_id"])
        for location in locations:
            self.assertEqual(
                location.warehouse_id,
                warehouse,
                f"{location.complete_name} points at the wrong warehouse",
            )

    def _create_branch(self, parent):
        zone = self.StockLocationObj.create(
            {"name": "Zone", "location_id": parent.id, "usage": "view"},
        )
        shelf = self.StockLocationObj.create({"name": "Shelf", "location_id": zone.id})
        bin_ = self.StockLocationObj.create({"name": "Bin", "location_id": shelf.id})
        self.env.flush_all()
        return zone, shelf, bin_

    def test_reparenting_a_subtree_repoints_every_descendant(self):
        warehouse_2 = self.env["stock.warehouse"].create(
            {"name": "Reparent WH", "code": "RPW"},
        )
        branch = self._create_branch(self.stock_location)
        self._assert_warehouse(self.StockLocationObj.union(*branch), self.warehouse_1)

        branch[0].location_id = warehouse_2.lot_stock_id
        self._assert_warehouse(self.StockLocationObj.union(*branch), warehouse_2)

    def test_repointing_a_warehouse_view_repoints_the_whole_subtree(self):
        zone, shelf, bin_ = self._create_branch(self.warehouse_1.view_location_id)
        warehouse_2 = self.env["stock.warehouse"].create(
            {"name": "Adopting WH", "code": "ADW"},
        )
        old_view = warehouse_2.view_location_id

        warehouse_2.view_location_id = zone

        self._assert_warehouse(zone | shelf | bin_, warehouse_2)
        self.assertTrue(old_view.exists())

    def test_creating_a_warehouse_on_an_existing_subtree_stamps_it_whole(self):
        view = self.StockLocationObj.create({"name": "Supplied View", "usage": "view"})
        zone = self.StockLocationObj.create(
            {"name": "Zone", "location_id": view.id, "usage": "view"},
        )
        shelf = self.StockLocationObj.create({"name": "Shelf", "location_id": zone.id})
        self.env.flush_all()

        warehouse = self.env["stock.warehouse"].create(
            {"name": "Supplied WH", "code": "SUP", "view_location_id": view.id},
        )

        self.assertEqual(warehouse.view_location_id, view)
        self._assert_warehouse(view | zone | shelf, warehouse)

    def test_creating_with_child_ids_maintains_descendants(self):
        parent = self.StockLocationObj.create(
            {
                "name": "Parent",
                "location_id": self.stock_location.id,
                "usage": "view",
                "child_ids": [(0, 0, {"name": "Born Child"})],
            },
        )
        self._assert_warehouse(parent | parent.child_ids, self.warehouse_1)

    def test_unlink_guard_stands_down_during_module_uninstall(self):
        parent = self.StockLocationObj.create(
            {"name": "Doomed", "location_id": self.stock_location.id, "usage": "view"},
        )
        child = self.StockLocationObj.create(
            {"name": "Doomed Child", "location_id": parent.id},
        )
        with self.assertRaises(UserError):
            parent.unlink()

        parent.with_context(_force_unlink=True).unlink()
        self.assertFalse(parent.exists())
        self.assertFalse(child.exists())


@tagged("post_install", "-at_install")
class TestStockLocationConstraintScope(TestStockCommon):
    def test_a_location_holding_stock_cannot_become_a_view(self):
        with_stock = self.StockLocationObj.create(
            {"name": "Occupied", "location_id": self.stock_location.id},
        )
        self.env["stock.quant"].create(
            {
                "product_id": self.productA.id,
                "location_id": with_stock.id,
                "quantity": 7,
            },
        )
        empty_location = self.StockLocationObj.create(
            {"name": "Vacant", "location_id": self.stock_location.id},
        )
        with self.assertRaises(UserError):
            (with_stock | empty_location).write({"usage": "view"})


@tagged("post_install", "-at_install")
class TestStockLocationFieldBounds(TestStockCommon):
    def test_display_name_is_the_stored_complete_name(self):
        zone = self.StockLocationObj.create(
            {"name": "Named", "location_id": self.stock_location.id, "usage": "view"},
        )
        leaf = self.StockLocationObj.create({"name": "Leaf", "location_id": zone.id})
        for location in (self.stock_location, zone, leaf, self.customer_location):
            self.assertEqual(location.display_name, location.complete_name)

    def test_formatted_display_name_still_marks_up_the_two_halves(self):
        leaf = self.StockLocationObj.create(
            {"name": "Leaf", "location_id": self.stock_location.id},
        )
        formatted = leaf.with_context(formatted_display_name=True).display_name
        self.assertEqual(
            formatted, f"--{self.stock_location.complete_name}/--{leaf.name}"
        )

    def test_cyclic_inventory_frequency_is_refused_at_write_time(self):
        with self.assertRaises(ValidationError):
            self.shelf_1.cyclic_inventory_frequency = 10**9
        with self.assertRaises(ValidationError):
            self.StockLocationObj.create(
                {
                    "name": "Too Frequent",
                    "location_id": self.stock_location.id,
                    "cyclic_inventory_frequency": 10**9,
                },
            )

        self.shelf_1.cyclic_inventory_frequency = 36500
        self.shelf_1.flush_recordset()
        self.assertTrue(self.shelf_1.next_inventory_date)

    @mute_logger("odoo.db.cursor")
    def test_cyclic_inventory_frequency_is_bounded_in_sql(self):
        with self.assertRaises(CheckViolation), self.env.cr.savepoint():
            self.env.cr.execute(
                "UPDATE stock_location SET cyclic_inventory_frequency = %s WHERE id = %s",
                (10**9, self.shelf_1.id),
            )

    @mute_logger("odoo.db.cursor")
    def test_barcode_is_unique_among_shared_locations(self):
        self.StockLocationObj.create(
            {"name": "Shared A", "barcode": "SHARED-BC", "company_id": False},
        )
        with self.assertRaises(UniqueViolation), self.env.cr.savepoint():
            self.StockLocationObj.create(
                {"name": "Shared B", "barcode": "SHARED-BC", "company_id": False},
            )
            self.env.flush_all()


@tagged("post_install", "-at_install")
class TestOutgoingWithoutMasterData(TestStockCommon):
    def test_is_outgoing_answers_when_the_inter_company_location_is_gone(self):
        self.env["ir.model.data"].search(
            [("module", "=", "stock"), ("name", "=", "stock_location_inter_company")],
        ).unlink()
        self.env.registry.clear_cache()

        self.assertTrue(self.customer_location._is_outgoing())
        self.assertFalse(self.stock_location._is_outgoing())


@tagged("post_install", "-at_install")
class TestIsEmptyTracksItsQuants(LocationCase):
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

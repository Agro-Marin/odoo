from odoo.exceptions import ValidationError
from odoo.tests import tagged

from odoo.addons.stock.tests.common import TestStockCommon


@tagged("post_install", "-at_install")
class TestLocationSubtreeCost(TestStockCommon):
    def _fan(self, name, width):
        zone = self.StockLocationObj.create(
            {"name": name, "location_id": self.stock_location.id, "usage": "view"},
        )
        self.StockLocationObj.create(
            [
                {"name": f"{name}-{index:03d}", "location_id": zone.id}
                for index in range(width)
            ],
        )
        self.env.flush_all()
        return zone

    def _queries_to_read_the_fan(self, name, width):
        zone = self._fan(name, width)
        locations = zone | zone.child_ids
        self.env.invalidate_all()
        before = self.env.cr.sql_statement_count
        locations.mapped("child_internal_location_ids")
        return self.env.cr.sql_statement_count - before

    def test_reading_the_field_over_a_recordset_is_one_query(self):
        narrow = self._queries_to_read_the_fan("Narrow", 5)
        wide = self._queries_to_read_the_fan("Wide", 40)
        self.assertLessEqual(
            wide,
            narrow + 1,
            "the compute costs a query per location: reading 41 of them cost "
            f"{wide} where reading 6 cost {narrow}",
        )

    def test_the_field_holds_this_location_and_its_internal_descendants(self):
        zone = self._fan("Holds", 3)
        shelf = zone.child_ids[0]
        deep_view = self.StockLocationObj.create(
            {"name": "Holds-view", "location_id": shelf.id, "usage": "view"},
        )
        deep_leaf = self.StockLocationObj.create(
            {"name": "Holds-leaf", "location_id": deep_view.id},
        )
        self.env.flush_all()

        self.assertEqual(
            zone.child_internal_location_ids,
            zone.child_ids | deep_leaf,
            "a view location is excluded, its internal descendants are not",
        )
        self.assertIn(shelf, shelf.child_internal_location_ids)

    def test_its_order_is_the_model_order(self):
        zone = self._fan("Ordered", 6)
        self.assertEqual(
            zone.child_internal_location_ids.ids,
            self.StockLocationObj.search(
                [("id", "child_of", zone.id), ("usage", "=", "internal")],
            ).ids,
            "callers take the first candidate when putaway finds nothing",
        )

    def test_a_location_that_becomes_a_view_stops_answering_with_itself(self):
        shelf = self.StockLocationObj.create(
            {"name": "Turncoat", "location_id": self.stock_location.id},
        )
        self.assertIn(shelf, shelf.child_internal_location_ids)

        shelf.usage = "view"

        self.assertNotIn(
            shelf,
            shelf.child_internal_location_ids,
            "the compute reads its own `usage`, so writing it must refresh it",
        )

    def test_a_grandchild_changing_type_refreshes_its_grandparent(self):
        zone = self._fan("Deep", 1)
        shelf = zone.child_ids
        leaf = self.StockLocationObj.create(
            {"name": "Deep-leaf", "location_id": shelf.id},
        )
        self.env.flush_all()
        self.assertIn(leaf, zone.child_internal_location_ids)

        leaf.usage = "view"

        self.assertNotIn(leaf, zone.child_internal_location_ids)

    def test_adopting_a_location_refreshes_its_new_parent(self):
        zone = self._fan("Adopting", 1)
        orphan = self.StockLocationObj.create(
            {"name": "Adopted", "location_id": self.stock_location.id},
        )
        self.env.flush_all()
        self.assertNotIn(orphan, zone.child_internal_location_ids)

        orphan.location_id = zone

        self.assertIn(orphan, zone.child_internal_location_ids)

    def test_creating_a_location_refreshes_its_parent(self):
        zone = self._fan("Newborn", 1)
        self.assertEqual(len(zone.child_internal_location_ids), 1)

        born = self.StockLocationObj.create(
            {"name": "Newborn-child", "location_id": zone.id},
        )

        self.assertIn(born, zone.child_internal_location_ids)

    def test_deleting_a_location_refreshes_its_parent(self):
        zone = self._fan("Doomed", 2)
        doomed = zone.child_ids[0]
        self.assertIn(doomed, zone.child_internal_location_ids)

        doomed.unlink()

        self.assertNotIn(doomed, zone.child_internal_location_ids)


@tagged("post_install", "-at_install")
class TestLocationWarehouseIsSelfMaintaining(TestStockCommon):
    def _branch(self, parent, name):
        zone = self.StockLocationObj.create(
            {"name": f"{name}-zone", "location_id": parent.id, "usage": "view"},
        )
        shelf = self.StockLocationObj.create(
            {"name": f"{name}-shelf", "location_id": zone.id},
        )
        leaf = self.StockLocationObj.create(
            {"name": f"{name}-leaf", "location_id": shelf.id},
        )
        self.env.flush_all()
        return zone | shelf | leaf

    def _stored_warehouse(self, locations):
        locations.invalidate_recordset(["warehouse_id"])
        return locations.mapped("warehouse_id")

    def test_a_new_branch_inherits_the_warehouse_at_every_depth(self):
        branch = self._branch(self.stock_location, "Fresh")
        self.assertEqual(self._stored_warehouse(branch), self.warehouse_1)

    def test_reparenting_a_branch_repoints_every_depth_of_it(self):
        other = self.env["stock.warehouse"].create(
            {"name": "Audit Reparent", "code": "ARP"},
        )
        branch = self._branch(self.stock_location, "Moving")

        branch[0].location_id = other.lot_stock_id

        self.assertEqual(self._stored_warehouse(branch), other)

    def test_a_warehouse_adopting_a_view_repoints_the_whole_subtree(self):
        branch = self._branch(self.warehouse_1.view_location_id, "Adopted")
        other = self.env["stock.warehouse"].create(
            {"name": "Audit Adopt", "code": "AAD"},
        )

        other.view_location_id = branch[0]

        self.assertEqual(self._stored_warehouse(branch), other)

    def test_a_warehouse_created_over_an_existing_subtree_stamps_it_whole(self):
        view = self.StockLocationObj.create(
            {"name": "Pre-existing", "usage": "view"},
        )
        branch = self._branch(view, "Pre")

        warehouse = self.env["stock.warehouse"].create(
            {"name": "Audit Supplied", "code": "ASP", "view_location_id": view.id},
        )

        self.assertEqual(self._stored_warehouse(view | branch), warehouse)

    def test_archiving_a_warehouse_repoints_its_subtree(self):
        host = self.env["stock.warehouse"].create(
            {"name": "Audit Host", "code": "AHO"},
        )
        inner = self.env["stock.warehouse"].create(
            {"name": "Audit Inner", "code": "AIN2"},
        )
        inner.view_location_id.location_id = host.lot_stock_id
        branch = self._branch(inner.lot_stock_id, "Doomed")
        self.assertEqual(self._stored_warehouse(branch), inner)

        inner.active = False

        self.assertEqual(
            self._stored_warehouse(branch.exists()),
            host,
            "the subtree still points at an archived warehouse",
        )

    def test_the_closest_warehouse_wins_over_the_further_one(self):
        inner = self.env["stock.warehouse"].create(
            {"name": "Audit Inner", "code": "AIN"},
        )
        inner.view_location_id.location_id = self.stock_location
        branch = self._branch(inner.lot_stock_id, "Nested")

        self.assertEqual(self._stored_warehouse(branch), inner)
        self.assertEqual(
            self._stored_warehouse(inner.view_location_id),
            inner,
            "a warehouse view answers with its own warehouse, not its host's",
        )


@tagged("post_install", "-at_install")
class TestReplenishLocationConstraint(TestStockCommon):
    def _detached_branch(self, name):
        parent = self.StockLocationObj.create(
            {"name": f"{name} parent", "company_id": False},
        )
        child = self.StockLocationObj.create(
            {"name": f"{name} child", "location_id": parent.id},
        )
        self.env.flush_all()
        return parent, child

    def test_a_descendant_cannot_also_be_a_replenish_location(self):
        parent, child = self._detached_branch("Descendant")
        parent.replenish_location = True

        with self.assertRaises(ValidationError):
            child.replenish_location = True

    def test_an_ancestor_cannot_also_be_a_replenish_location(self):
        parent, child = self._detached_branch("Ancestor")
        child.replenish_location = True

        with self.assertRaises(ValidationError):
            parent.replenish_location = True

    def test_the_refusal_names_the_conflicting_location_in_full(self):
        grandparent = self.StockLocationObj.create(
            {"name": "Named", "company_id": False, "usage": "view"},
        )
        parent = self.StockLocationObj.create(
            {"name": "Stock", "location_id": grandparent.id, "company_id": False},
        )
        child = self.StockLocationObj.create(
            {"name": "Named child", "location_id": parent.id, "company_id": False},
        )
        self.env.flush_all()
        parent.replenish_location = True
        self.assertNotEqual(parent.complete_name, parent.name)

        with self.assertRaises(ValidationError) as caught:
            child.replenish_location = True

        self.assertIn(parent.complete_name, str(caught.exception))

    def test_a_sibling_branch_is_free_to_be_one(self):
        left, __ = self._detached_branch("Left")
        right, __ = self._detached_branch("Right")

        left.replenish_location = True
        right.replenish_location = True
        self.env.flush_all()

        self.assertTrue(left.replenish_location)
        self.assertTrue(right.replenish_location)

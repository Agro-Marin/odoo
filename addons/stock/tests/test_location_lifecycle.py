from odoo.exceptions import UserError
from odoo.tests.common import tagged

from odoo.addons.stock.tests.common import LocationCase, TestStockCommon


@tagged("post_install", "-at_install")
class TestArchivingCannotBeWaivedFromTheContext(LocationCase):
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
class TestDeletingIsGovernedLikeArchiving(LocationCase):
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
class TestUsageConversionAsksOnce(LocationCase):
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
class TestLocationGuardMessages(TestStockCommon):
    def test_unlink_names_the_location_that_holds_the_children(self):
        childless, parent = self.StockLocationObj.create(
            [
                {"name": "AAA childless", "location_id": self.stock_location.id},
                {"name": "ZZZ parent", "location_id": self.stock_location.id},
            ],
        )
        self.StockLocationObj.create(
            [
                {"name": "Kid one", "location_id": parent.id},
                {"name": "Kid two", "location_id": parent.id},
            ],
        )
        self.env.flush_all()

        with self.assertRaises(UserError) as caught:
            (childless | parent).unlink()

        message = str(caught.exception)
        self.assertIn(parent.display_name, message)
        self.assertNotIn(childless.display_name, message)
        self.assertIn("2 sub-location", message)

    def test_converting_a_stocked_location_names_it(self):
        empty, stocked = self.StockLocationObj.create(
            [
                {"name": "Vacant one", "location_id": self.stock_location.id},
                {"name": "Stocked one", "location_id": self.stock_location.id},
            ],
        )
        self.env["stock.quant"].create(
            {
                "product_id": self.productA.id,
                "location_id": stocked.id,
                "quantity": 4,
            },
        )
        self.env.flush_all()

        with self.assertRaises(UserError) as caught:
            (empty | stocked).write({"usage": "transit"})

        message = str(caught.exception)
        self.assertIn(stocked.display_name, message)
        self.assertNotIn(empty.display_name, message)
        self.assertNotIn(
            "Internal locations",
            message,
            "neither location is internal-bound; the old message said they were",
        )

    def test_a_view_refuses_an_empty_quant_a_transit_accepts_it(self):
        location = self.StockLocationObj.create(
            {"name": "Zero quant", "location_id": self.stock_location.id},
        )
        self.env["stock.quant"].create(
            {
                "product_id": self.productA.id,
                "location_id": location.id,
                "quantity": 0,
            },
        )
        self.env.flush_all()

        with self.assertRaises(UserError):
            location.write({"usage": "view"})

        location.write({"usage": "transit"})
        self.assertEqual(location.usage, "transit")

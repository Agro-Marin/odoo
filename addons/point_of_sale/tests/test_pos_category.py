from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.tests import tagged

from odoo.addons.point_of_sale.tests.common import TestPoSCommon


@tagged("post_install", "-at_install")
class TestPosCategoryProducts(TestPoSCommon):
    def _category(self, name, parent=None):
        return self.env["pos.category"].create(
            {"name": name, "parent_id": parent.id if parent else False}
        )

    def _product(self, name, categories):
        return self.env["product.template"].create(
            {
                "name": name,
                "available_in_pos": True,
                "pos_categ_ids": [Command.set(categories.ids)],
            }
        )

    def test_product_count_counts_descendants_once(self):
        """A category reports the products of its whole subtree, and a product
        filed under both a parent and its child is counted once."""
        parent = self._category("Drinks")
        child = self._category("Sodas", parent=parent)
        other = self._category("Food")

        self._product("Bottled Water", parent)
        self._product("Cola", child)
        self._product("Sparkling Water", parent | child)
        self._product("Bread", other)

        self.assertEqual(parent.product_count, 3)
        self.assertEqual(child.product_count, 2)
        self.assertEqual(other.product_count, 1)

    def test_product_count_is_zero_for_an_empty_category(self):
        self.assertEqual(self._category("Empty").product_count, 0)

    def test_action_open_associated_products_filters_on_the_category(self):
        """The smart button opens the POS product list already filtered, and
        keeps the context the action carries on its own."""
        categ = self._category("Drinks")
        action = categ.action_open_associated_products()

        self.assertEqual(action["res_model"], "product.template")
        self.assertEqual(action["context"]["search_default_pos_categ_ids"], [categ.id])
        self.assertEqual(action["context"]["default_pos_categ_ids"], [categ.id])
        # The action's own context must survive being extended.
        self.assertTrue(action["context"]["default_available_in_pos"])


@tagged("post_install", "-at_install")
class TestPosArchiveWithOpenSession(TestPoSCommon):
    """A register that cannot sell a product should not stop us archiving it."""

    def setUp(self):
        super().setUp()
        self.config = self.basic_config
        self.sold_categ = self.env["pos.category"].create({"name": "Sold here"})
        self.other_categ = self.env["pos.category"].create({"name": "Not sold here"})
        # The open register is restricted to `sold_categ`, so nothing filed
        # under `other_categ` is loaded by it.
        self.config.write(
            {
                "limit_categories": True,
                "iface_available_categ_ids": [Command.set(self.sold_categ.ids)],
            }
        )
        self.open_new_session()

    def _pos_product(self, name, categ):
        return self.env["product.template"].create(
            {
                "name": name,
                "available_in_pos": True,
                "pos_categ_ids": [Command.set(categ.ids)],
            }
        )

    def test_archive_product_the_open_register_cannot_sell(self):
        product = self._pos_product("Discontinued", self.other_categ)
        product.action_archive()
        self.assertFalse(product.active)

    def test_delete_product_the_open_register_cannot_sell(self):
        product = self._pos_product("Discontinued", self.other_categ)
        product.unlink()

    def test_archive_product_the_open_register_sells_is_still_refused(self):
        product = self._pos_product("On the shelf", self.sold_categ)
        with self.assertRaises(UserError):
            product.action_archive()

    def test_archive_is_refused_when_a_register_loads_every_category(self):
        self.config.limit_categories = False
        product = self._pos_product("Discontinued", self.other_categ)
        with self.assertRaises(UserError):
            product.action_archive()

    def test_delete_variant_the_open_register_cannot_sell(self):
        product = self._pos_product("Discontinued", self.other_categ)
        product.product_variant_ids.unlink()

    def test_category_guard_still_refuses_a_loaded_category(self):
        """The category side already worked; it must keep working."""
        with self.assertRaises(UserError):
            self.sold_categ.unlink()

    def test_category_guard_still_refuses_a_printer_category(self):
        printer_categ = self.env["pos.category"].create({"name": "Kitchen"})
        printer = self.env["pos.printer"].create(
            {
                "name": "Kitchen printer",
                "proxy_ip": "192.168.0.1",
                "product_categories_ids": [Command.set(printer_categ.ids)],
            }
        )
        self.config.printer_ids = [Command.set(printer.ids)]
        with self.assertRaises(UserError):
            printer_categ.unlink()

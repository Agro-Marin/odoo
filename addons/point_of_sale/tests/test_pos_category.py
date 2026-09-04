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

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestInventoryMenuNames(TransactionCase):
    """Ctrl+K searches menus by name, so two Inventory menus that read the same
    are two results the user cannot tell apart."""

    def _inventory_menu_names(self, user):
        root = self.env.ref("stock.menu_stock_root")
        names = []
        for menu in self.env["ir.ui.menu"].with_user(user).search([]):
            parent = menu.parent_id
            while parent:
                if parent == root:
                    names.append(menu.name)
                    break
                parent = parent.parent_id
        return names

    def test_the_two_location_menus_read_differently(self):
        """One lives under Reporting and one under Configuration, and the same
        user sees both: Configuration is gated on storage locations, and
        Reporting's groups are OR-ed, storage locations among them."""
        user = self.env["res.users"].create(
            {
                "name": "Multi location manager",
                "login": "inventory_menu_probe",
                "group_ids": [
                    (
                        6,
                        0,
                        [
                            self.env.ref("stock.group_stock_manager").id,
                            self.env.ref("stock.group_stock_multi_locations").id,
                        ],
                    ),
                ],
            }
        )
        names = self._inventory_menu_names(user)
        self.assertIn(
            self.env.ref("stock.menu_action_location_form").with_user(user).name,
            names,
            "the fixture needs the Configuration menu to be visible",
        )
        self.assertEqual(
            names.count("Locations"),
            1,
            "Inventory offers two menus called Locations, and the global search "
            "cannot tell them apart",
        )

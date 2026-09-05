from odoo.modules.module import get_module_icon_path
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestProductExpiryModuleIcon(TransactionCase):
    def test_module_resolves_to_its_own_icon(self):
        self.assertEqual(
            get_module_icon_path("product_expiry"),
            "/product_expiry/static/description/icon.png",
        )

    def test_apps_list_does_not_fall_back_to_the_base_placeholder(self):
        modules = self.env["ir.module.module"].search(
            [("name", "in", ["product_expiry", "base"])]
        )
        icons = {m.name: m.icon_image for m in modules}
        self.assertTrue(icons.get("product_expiry"))
        self.assertNotEqual(icons["product_expiry"], icons["base"])

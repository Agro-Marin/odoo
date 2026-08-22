from odoo.tests.common import TransactionCase, tagged
from odoo.tools.assets.esm_registry import esm_registry, validate_esm_config


@tagged("post_install", "-at_install")
class TestEsmRegistration(TransactionCase):

    BUNDLE = "point_of_sale.assets_debug"
    PARENTS = ("point_of_sale.assets_prod", "point_of_sale.assets_prod_dark")

    def test_assets_debug_is_registered(self):
        self.assertIn(self.BUNDLE, esm_registry().bundles)

    def test_assets_debug_is_secondary_of_both_prod_bundles(self):
        reg = esm_registry()
        for parent in self.PARENTS:
            self.assertIn(self.BUNDLE, reg.secondary_import_map_includes[parent])
        self.assertCountEqual(reg.secondary_parents[self.BUNDLE], self.PARENTS)

    def test_assets_debug_is_not_an_import_map_include(self):
        self.assertNotIn(self.BUNDLE, esm_registry().import_map_included_bundles)

    def test_unregistered_child_is_rejected(self):
        reg = esm_registry()
        with self.assertRaises(ValueError):
            validate_esm_config(
                reg.bundles,
                reg.dynamic_children,
                reg.import_map_includes,
                {"point_of_sale.assets_prod": ["point_of_sale.does_not_exist"]},
            )

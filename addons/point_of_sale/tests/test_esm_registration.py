# Part of Odoo. See LICENSE file for full copyright and licensing details.
from odoo.tests.common import TransactionCase, tagged
from odoo.tools.assets.esm_registry import esm_registry, validate_esm_config


@tagged("post_install", "-at_install")
class TestEsmRegistration(TransactionCase):
    """Point of Sale bundles carrying module-syntax JS are declared ESM."""

    BUNDLE = "point_of_sale.assets_debug"
    PARENTS = ("point_of_sale.assets_prod", "point_of_sale.assets_prod_dark")

    def test_assets_debug_is_registered(self):
        """The fake-tour bundle is an ESM bundle, not a legacy one."""
        # Undeclared, AssetsBundle routes it as legacy and the JS pipeline
        # replaces every module-syntax file with a console.error stub. Nothing
        # raises and the build succeeds, so the only symptom is Owl templates
        # that never register — here, a missing point_of_sale.Loader.
        self.assertIn(self.BUNDLE, esm_registry().bundles)

    def test_assets_debug_is_secondary_of_both_prod_bundles(self):
        """Both colour schemes bridge the debug bundle to the running app."""
        # pos_assets_index.xml renders assets_prod or assets_prod_dark based on
        # the pos_color_scheme cookie, and whichever comes first owns the page's
        # import map. Declaring only one leaves the other mode unbridged, which
        # breaks in exactly half the sessions.
        reg = esm_registry()
        for parent in self.PARENTS:
            self.assertIn(self.BUNDLE, reg.secondary_import_map_includes[parent])
        self.assertCountEqual(reg.secondary_parents[self.BUNDLE], self.PARENTS)

    def test_assets_debug_is_not_an_import_map_include(self):
        """The debug bundle needs compiling, so it cannot ride the other key."""
        # An import_map_includes child is never compiled at all:
        # EsbuildCompiler.compile returns an empty result at esbuild.py:481 when
        # _import_map_included is set. Only secondary_import_map_includes both
        # compiles the satellite and aliases its shared specifiers onto the
        # parent's odoo.loader.modules instances. Neither key raises, so nothing
        # but this assertion separates them.
        self.assertNotIn(self.BUNDLE, esm_registry().import_map_included_bundles)

    def test_unregistered_child_is_rejected(self):
        """A mapping naming a bundle nobody declared fails validation."""
        reg = esm_registry()
        with self.assertRaises(ValueError):
            validate_esm_config(
                reg.bundles,
                reg.dynamic_children,
                reg.import_map_includes,
                {"point_of_sale.assets_prod": ["point_of_sale.does_not_exist"]},
            )

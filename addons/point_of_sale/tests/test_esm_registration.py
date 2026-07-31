# Part of Odoo. See LICENSE file for full copyright and licensing details.
from odoo.tests.common import TransactionCase, tagged
from odoo.tools.assets.esm_registry import esm_registry, validate_esm_config


@tagged("post_install", "-at_install")
class TestEsmRegistration(TransactionCase):
    """Point of Sale bundles carrying module-syntax JS are declared ESM."""

    def test_assets_debug_is_registered(self):
        """The fake-tour bundle is an ESM bundle, not a legacy one."""
        # Undeclared, AssetsBundle routes it as legacy and the JS pipeline
        # replaces every module-syntax file with a console.error stub. Nothing
        # raises and the build succeeds, so the only symptom is Owl templates
        # that never register — here, a missing point_of_sale.Loader.
        self.assertIn("point_of_sale.assets_debug", esm_registry().bundles)

    def test_assets_debug_is_secondary_of_both_prod_bundles(self):
        """Both colour schemes bridge the debug bundle to the running app."""
        # pos_assets_index.xml renders assets_prod or assets_prod_dark based on
        # the pos_color_scheme cookie, and whichever comes first owns the page's
        # import map. Declaring only one leaves the other mode unbridged, which
        # breaks in exactly half the sessions.
        parents = ("point_of_sale.assets_prod", "point_of_sale.assets_prod_dark")
        secondary = esm_registry().secondary_import_map_includes
        for parent in parents:
            self.assertIn("point_of_sale.assets_debug", secondary[parent])
        self.assertCountEqual(
            esm_registry().secondary_parents["point_of_sale.assets_debug"],
            parents,
        )

    def test_live_registry_still_validates(self):
        """The aggregated taxonomy stays consistent after these additions."""
        reg = esm_registry()
        validate_esm_config(
            reg.bundles,
            reg.dynamic_children,
            reg.import_map_includes,
            reg.secondary_import_map_includes,
        )

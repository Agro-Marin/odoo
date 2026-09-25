from odoo.tests import tagged

from odoo.addons.web.tests.bundle_services import BundleServicesCase, sources_outside

# web's hook libraries (hooks.js, action_port.js, ...) call useService() in bodies
# that run only when a component calls the hook; web's own bundles pin web.
POS_SOURCES = sources_outside("web")


@tagged("-at_install", "post_install")
class TestPosBundleServices(BundleServicesCase):
    def test_every_pos_bundle_starts_the_services_its_components_require(self):
        for bundle in (
            "point_of_sale._assets_pos",
            "point_of_sale.assets_prod",
            "point_of_sale.customer_display_assets",
        ):
            with self.subTest(bundle=bundle):
                self.assertBundleStartsRequiredServices(bundle, POS_SOURCES)

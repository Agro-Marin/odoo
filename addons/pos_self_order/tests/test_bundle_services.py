from odoo.tests import tagged

from odoo.addons.point_of_sale.tests.test_bundle_services import POS_SOURCES
from odoo.addons.web.tests.bundle_services import BundleServicesCase

DORMANT = {
    # StandNumberPage, the only self-order screen mounting Numpad, passes onClick;
    # Numpad takes number_buffer only without one.
    "/point_of_sale/static/src/app/components/numpad/numpad.js": {"number_buffer"},
    # Bundled through product_card/*, but no self-order component mounts ProductCard.
    "/point_of_sale/static/src/app/components/product_card/product_card.js": {
        "contextual_utils_service",
        "pos",
        "pos_stock",
    },
}


@tagged("-at_install", "post_install")
class TestSelfOrderBundleServices(BundleServicesCase):
    def test_self_order_app_starts_the_services_its_components_require(self):
        self.assertBundleStartsRequiredServices(
            "pos_self_order.assets", POS_SOURCES, DORMANT
        )

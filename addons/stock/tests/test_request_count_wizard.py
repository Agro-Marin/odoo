from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestRequestCountWizard(HttpCase):
    def test_responsible_is_shown_with_avatar(self):
        product = self.env["product.product"].create(
            {
                "name": "Counted Widget",
                "is_storable": True,
            }
        )
        self.env["stock.quant"].create(
            {
                "product_id": product.id,
                "location_id": self.env.ref("stock.stock_location_stock").id,
                "inventory_quantity": 1.0,
            }
        )
        self.start_tour(
            "/odoo/action-stock.action_view_inventory_tree",
            "test_request_count_shows_avatar",
            login="admin",
        )

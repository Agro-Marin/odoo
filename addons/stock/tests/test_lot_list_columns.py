from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestLotListColumns(HttpCase):
    def test_default_columns_show_the_quantity(self):
        product = self.env["product.product"].create(
            {
                "name": "Tracked Widget",
                "is_storable": True,
                "tracking": "lot",
            }
        )
        self.env["stock.lot"].create(
            {
                "name": "LOT-0001",
                "product_id": product.id,
            }
        )
        self.start_tour(
            "/odoo/action-stock.action_stock_lot_form",
            "test_lot_list_default_columns",
            login="admin",
        )

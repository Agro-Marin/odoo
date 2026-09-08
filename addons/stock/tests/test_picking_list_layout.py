from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestPickingListLayout(HttpCase):
    def test_priority_column_is_star_sized(self):
        product = self.env["product.product"].create(
            {
                "name": "Widget",
                "is_storable": True,
            }
        )
        picking_type = self.env.ref("stock.picking_type_out")
        self.env["stock.picking"].create(
            {
                "picking_type_id": picking_type.id,
                "location_id": picking_type.default_location_src_id.id,
                "location_dest_id": picking_type.default_location_dest_id.id,
                "move_ids": [
                    (
                        0,
                        0,
                        {
                            "product_id": product.id,
                            "product_uom_qty": 1.0,
                        },
                    )
                ],
            }
        )
        self.start_tour(
            "/odoo/action-stock.action_picking_tree_all",
            "test_stock_picking_priority_column_width",
            login="admin",
        )

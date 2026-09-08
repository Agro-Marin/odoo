from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestDashboardCards(HttpCase):
    def test_overview_card_has_no_operations_link(self):
        picking_type = self.env.ref("stock.picking_type_out")
        product = self.env["product.product"].create(
            {
                "name": "Reserved Widget",
                "is_storable": True,
            }
        )
        self.env["stock.quant"]._update_available_quantity(
            product, picking_type.default_location_src_id, 10.0
        )
        picking = self.env["stock.picking"].create(
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
        picking.action_confirm()
        picking.action_assign()
        self.assertEqual(
            picking.move_ids.state,
            "assigned",
            "the fixture needs a ready move, or the removed link was invisible anyway",
        )
        self.start_tour(
            "/odoo/action-stock.stock_picking_type_action",
            "test_dashboard_has_no_operations_link",
            login="admin",
        )

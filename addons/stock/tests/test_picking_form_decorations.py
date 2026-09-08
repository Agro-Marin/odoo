from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestPickingFormDecorations(HttpCase):
    def test_new_transfer_is_not_painted_overdue(self):
        self.start_tour(
            "/odoo/action-stock.action_picking_tree_all",
            "test_new_picking_is_never_late",
            login="admin",
        )

    def test_saved_overdue_transfer_is_still_marked(self):
        """The guard is on `id`, not on the comparison: a real late transfer
        must keep reading as late."""
        picking_type = self.env.ref("stock.picking_type_out")
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": picking_type.id,
                "location_id": picking_type.default_location_src_id.id,
                "location_dest_id": picking_type.default_location_dest_id.id,
            }
        )
        picking.date_planned = "2020-01-01 08:00:00"
        self.start_tour(
            f"/odoo/action-stock.action_picking_tree_all/{picking.id}",
            "test_saved_late_picking_is_marked",
            login="admin",
        )

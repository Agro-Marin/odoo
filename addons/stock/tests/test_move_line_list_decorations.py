from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestMoveLineListDecorations(HttpCase):
    def _done_outgoing_line(self, product_name, quantity):
        """A done move line leaving stock, which is what Moves History lists.

        The action defaults to the Done filter, so the line has to reach that
        state; `_action_done` drops a line that moved nothing, so the zero case
        is built by hand and the move is marked done around it.
        """
        source = self.env.ref("stock.stock_location_stock")
        destination = self.env.ref("stock.stock_location_customers")
        product = self.env["product.product"].create(
            {
                "name": product_name,
                "is_storable": True,
            }
        )
        move = self.env["stock.move"].create(
            {
                "product_id": product.id,
                "product_uom_qty": 3.0,
                "location_id": source.id,
                "location_dest_id": destination.id,
            }
        )
        move._action_confirm()
        self.env["stock.move.line"].create(
            {
                "move_id": move.id,
                "product_id": product.id,
                "product_uom_id": product.uom_id.id,
                "quantity": quantity,
                "location_id": source.id,
                "location_dest_id": destination.id,
                "company_id": self.env.company.id,
            }
        )
        move.state = "done"

    def test_zero_quantity_is_not_coloured(self):
        self._done_outgoing_line("Alpha Widget", 3.0)
        self._done_outgoing_line("Bravo Widget", 0.0)
        self.start_tour(
            "/odoo/action-stock.stock_move_line_action",
            "test_moves_history_zero_is_neutral",
            login="admin",
        )

from odoo import Command
from odoo.tests import tagged

from .common import TestSaleStockCommon


@tagged("post_install", "-at_install")
class TestDeliveryLineMatch(TestSaleStockCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Match = cls.env["sale.delivery.line.match"]
        cls.storable = cls.env["product.product"].create(
            {"name": "match storable", "type": "consu", "is_storable": True}
        )

    def _all_rows(self):
        self.env.flush_all()
        return self.Match.search([])

    def _match_rows(self):
        self.env.flush_all()
        return self.Match.search([("partner_id", "=", self.partner.id)])

    def _create_sale(self, quantity=5.0):
        order = self.env["sale.order"].create(
            {
                "partner_id": self.partner.id,
                "line_ids": [
                    Command.create(
                        {
                            "product_id": self.storable.id,
                            "product_qty": quantity,
                            "price_unit": 20.0,
                            "tax_ids": [Command.clear()],
                        }
                    )
                ],
            }
        )
        order.action_confirm()
        return order

    def _unlink_moves(self, order):
        moves = order.picking_ids.move_ids
        moves.sale_line_id = False
        return moves

    def test_order_line_half_lists_outstanding_lines(self):
        order = self._create_sale()
        self._unlink_moves(order)
        rows = self._match_rows().filtered("order_line_id")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows.order_id, order)
        self.assertEqual(rows.qty_to_transfer, 5.0)

    def test_move_half_carries_a_partner_the_domain_can_filter_on(self):
        order = self._create_sale()
        moves = self._unlink_moves(order)
        rows = self._match_rows().filtered("move_id")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows.move_id, moves)
        self.assertEqual(
            rows.partner_id,
            self.partner,
            "every entry action filters by partner, so a move row without one "
            "is a move row nobody can see",
        )

    def test_match_links_move_to_line(self):
        order = self._create_sale()
        moves = self._unlink_moves(order)
        self._match_rows().action_match_lines()
        self.assertEqual(moves.sale_line_id, order.line_ids)

    def test_direction_is_outgoing_only(self):
        order = self._create_sale()
        self._unlink_moves(order)
        rows = self._all_rows().filtered("move_id")
        for row in rows:
            self.assertEqual(
                row.move_id.location_dest_id.usage,
                "customer",
                "a delivery matcher must not offer incoming moves",
            )

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestAllowedCarriersBatchCost(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        picking_type = cls.env["stock.picking.type"].search(
            [("code", "=", "outgoing")], limit=1
        )
        partner = cls.env["res.partner"].search([], limit=1)
        cls.pickings = cls.env["stock.picking"].create(
            [
                {"picking_type_id": picking_type.id, "partner_id": partner.id}
                for _ in range(20)
            ]
        )
        cls.env.flush_all()

    def _queries_for(self, count):
        records = self.pickings[:count]
        self.env.invalidate_all()
        before = self.env.cr.sql_log_count
        records.mapped("allowed_carrier_ids")
        return self.env.cr.sql_log_count - before

    def test_allowed_carrier_ids_does_not_query_per_picking(self):
        small = self._queries_for(2)
        large = self._queries_for(20)
        self.assertLessEqual(
            large,
            small,
            f"allowed_carrier_ids costs {large} queries for 20 pickings against "
            f"{small} for 2: it is searching per picking. Two sizes rather than "
            f"one, because a single size cannot tell a flat cost from a linear "
            f"one, and 2 rather than 1 so a warm cache cannot make it vacuous.",
        )

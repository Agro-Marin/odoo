from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestAllowedCarriersBatchCost(TransactionCase):
    """`allowed_carrier_ids` must cost the same whatever the picking count.

    The carrier search behind it varies only by company, so a picking list --
    many pickings, one or two companies -- must not pay a search per row. It
    used to: 28 queries for 20 pickings, against 9 now.

    Read through the field rather than by calling `_compute_allowed_carrier_ids`
    directly. A direct call runs outside `Field.compute_value`'s
    `env.protecting`, so assigning the field re-enters `__get__` for each record
    and the compute is invoked once per picking on top of the batch -- an
    artefact of the measurement, not of the ORM, and it hides what a reader
    actually pays.
    """

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
        # Not equality: the small read runs first and warms caches the large one
        # reuses, so the large size can legitimately cost less. It must not cost
        # more -- that is what a search per picking looks like from outside.
        self.assertLessEqual(
            large,
            small,
            f"allowed_carrier_ids costs {large} queries for 20 pickings against "
            f"{small} for 2: it is searching per picking. Two sizes rather than "
            f"one, because a single size cannot tell a flat cost from a linear "
            f"one, and 2 rather than 1 so a warm cache cannot make it vacuous.",
        )

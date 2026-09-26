from odoo import models
from odoo.exceptions import UserError

TRIP_MODES = (False, "own_fleet", "salesperson")


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def _get_dispatch_mode(self):
        """How the goods leave: the carrier's mode, else the source location's.

        :rtype: str or bool
        """
        self.check_singleton()
        return self.carrier_id.dispatch_mode or self.location_id.dispatch_mode

    def _requires_trip(self):
        # Goods that leave with a third-party carrier or the customer do not ride
        # in one of our trips; no carrier and no location mode still means our
        # own vehicle.
        return super()._requires_trip() and self._get_dispatch_mode() in TRIP_MODES

    def _check_dispatch_requirements(self):
        super()._check_dispatch_requirements()
        for picking in self:
            picking_type = picking.picking_type_id
            if not (
                picking_type.code == "outgoing" and picking_type.dispatch_batch_required
            ):
                continue
            if (
                picking._get_dispatch_mode() == "third_party"
                and not picking.carrier_tracking_ref
            ):
                raise UserError(
                    self.env._(
                        "Transfer %(name)s leaves with a third-party carrier: "
                        "capture its tracking reference before validating it.",
                        name=picking.name,
                    )
                )

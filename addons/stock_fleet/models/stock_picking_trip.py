from odoo import fields, models
from odoo.exceptions import UserError
from odoo.fields import Domain
from odoo.libs.debug_log import DebugLog

_debug = DebugLog(__name__)


class StockPickingType(models.Model):
    _inherit = "stock.picking.type"

    dispatch_batch_required = fields.Boolean(
        string="Deliver in Trips",
        tracking=True,
        help="Outgoing transfers of this type are validated only inside a trip that "
        "has departed with its vehicle, operator and supervisor.",
    )


class StockPicking(models.Model):
    _inherit = "stock.picking"

    delivery_failure_reason = fields.Text(
        copy=False,
        tracking=True,
        help="Why the goods came back undelivered on the last trip.",
    )

    def _requires_trip(self):
        """Whether this transfer may only be validated inside a departed trip.

        Bridges narrow it, e.g. by the carrier that takes the goods.

        :rtype: bool
        """
        self.check_singleton()
        picking_type = self.picking_type_id
        return bool(
            picking_type.code == "outgoing"
            and picking_type.dispatch_batch_required
            and not ("pos_session_id" in self._fields and self.pos_session_id)
        )

    def _check_dispatch_requirements(self):
        """Refuse to validate a transfer that must travel in a trip outside one.

        Reads the transfer's own batch: a batch validates its transfers twice, the
        first time without passing itself along.
        """
        for picking in self:
            if not picking._requires_trip():
                continue
            batch = picking.batch_id
            if not batch:
                raise UserError(
                    self.env._(
                        "Transfer %(name)s leaves on a vehicle and must be delivered "
                        "from a trip. Add it to a trip and register the departure first.",
                        name=picking.name,
                    )
                )
            if not batch.date_departure:
                raise UserError(
                    self.env._(
                        "Transfer %(name)s belongs to trip %(batch)s, which has not "
                        "departed. Register the departure first.",
                        name=picking.name,
                        batch=batch.name,
                    )
                )

    def _get_domain_possible_batches(self, excluded_batches=None):
        # Auto-batching must not board a transfer onto a trip that already left.
        return super()._get_domain_possible_batches(excluded_batches) & Domain(
            "date_departure", "=", False
        )

    def _check_before_validation(self, batch=None):
        self._check_dispatch_requirements()
        return super()._check_before_validation(batch=batch)

    def write(self, vals):
        if vals.get("batch_id"):
            trip = self.env["stock.picking.batch"].browse(vals["batch_id"])
            if trip.date_departure:
                trip._check_trip_takes_no_new_pickings(
                    self.filtered(lambda picking: picking.batch_id != trip)
                )
        # A departed trip is the record of what the vehicle carried: a delivered
        # transfer stays on it when the batch sheds its done transfers.
        if "batch_id" in vals and not vals["batch_id"]:
            kept = self.filtered(
                lambda picking: (
                    picking.state == "done" and picking.batch_id.date_departure
                )
            )
            if kept:
                rest = self - kept
                kept_vals = {
                    key: value for key, value in vals.items() if key != "batch_id"
                }
                if kept_vals:
                    super(StockPicking, kept).write(kept_vals)
                return super(StockPicking, rest).write(vals) if rest else True
        return super().write(vals)

    # ------------------------------------------------------------------
    # The driver's outcome per stop
    # ------------------------------------------------------------------
    def action_deliver(self):
        """Driver button: the customer received the goods as loaded."""
        self.check_singleton()
        if self.state != "assigned":
            raise UserError(
                self.env._(
                    "Transfer %(name)s is not ready to deliver (%(state)s).",
                    name=self.name,
                    state=dict(self._fields["state"].selection).get(self.state),
                )
            )
        if not self.batch_id.date_departure:
            raise UserError(
                self.env._("Transfer %s is not on a trip that has departed.", self.name)
            )
        self.move_ids.filtered(
            lambda move: move.state not in ("done", "cancel")
        ).picked = True
        return self.button_validate(skip_backorder=True)

    def action_not_delivered(self):
        """Driver button: the goods come back; ask why."""
        self.check_singleton()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Not delivered"),
            "res_model": "stock.picking.delivery.failure",
            "view_mode": "form",
            "target": "new",
            "context": {"default_picking_id": self.id},
        }

    def _register_delivery_failure(self, reason):
        """Take the transfer off its trip with the reason on both records.

        The transfer stays ready, in transit, for the next trip.

        :param str reason: why the goods were not delivered
        """
        self.check_singleton()
        batch = self.batch_id
        _debug.lifecycle("trip_delivery_failure", pickings=self, batches=batch)
        self.write({"delivery_failure_reason": reason, "batch_id": False})
        self.message_post(
            body=self.env._(
                "Not delivered on trip %(batch)s: %(reason)s",
                batch=batch.name or "-",
                reason=reason,
            )
        )
        if batch:
            batch.message_post(
                body=self.env._(
                    "%(picking)s came back undelivered: %(reason)s",
                    picking=self.name,
                    reason=reason,
                )
            )

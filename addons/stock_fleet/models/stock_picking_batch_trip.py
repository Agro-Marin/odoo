from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.libs.debug_log import DebugLog

_debug = DebugLog(__name__)

# Once a trip has left, these describe what left and who took it; they are the
# dispatch record and no later change of vehicle custody or form edit rewrites them.
FROZEN_AT_DEPARTURE = (
    "vehicle_id",
    "operator_id",
    "driver_id",
    "supervisor_id",
    "odometer_departure",
)
FROZEN_AT_RETURN = ("odometer_return",)


class StockPickingBatch(models.Model):
    _inherit = "stock.picking.batch"

    operator_id = fields.Many2one(
        comodel_name="hr.employee",
        string="Operator",
        tracking=True,
        help="Employee who drives this trip, chosen for each trip: who drives depends "
        "on the load and on who is free, not on who holds the vehicle. Frozen once "
        "the trip departs.",
    )
    supervisor_id = fields.Many2one(
        comodel_name="res.users",
        domain="[('share', '=', False)]",
        tracking=True,
        help="User who authorises the departure. It cannot be the operator.",
    )
    trip_state = fields.Selection(
        selection=[
            ("planned", "Planned"),
            ("in_transit", "In Transit"),
            ("closed", "Closed"),
            ("cancelled", "Cancelled"),
        ],
        compute="_compute_trip_state",
        store=True,
        index="btree_not_null",
        help="Where the trip stands, read from its departure and return stamps. "
        "Empty on batches whose operation type does not dispatch.",
    )
    date_departure = fields.Datetime(
        string="Departure",
        copy=False,
        readonly=True,
        tracking=True,
        help="When the vehicle left with this trip.",
    )
    date_return = fields.Datetime(
        string="Return",
        copy=False,
        readonly=True,
        tracking=True,
        help="When the trip was closed: the vehicle came back, or the last delivery "
        "was made where the trip does not return.",
    )
    departed_uid = fields.Many2one(
        comodel_name="res.users",
        string="Dispatched By",
        copy=False,
        readonly=True,
        help="User who registered the departure.",
    )
    odometer_departure = fields.Float(
        string="Odometer at Departure",
        copy=False,
        tracking=True,
    )
    odometer_return = fields.Float(
        string="Odometer at Return",
        copy=False,
        tracking=True,
    )
    odometer_uom_id = fields.Many2one(related="vehicle_id.odometer_uom_id")
    trip_delivered_count = fields.Integer(
        string="Delivered",
        compute="_compute_trip_counts",
    )
    trip_pending_count = fields.Integer(
        string="Pending",
        compute="_compute_trip_counts",
    )

    @api.depends("operator_id")
    def _compute_driver_id(self):
        # The vehicle's operator is whoever holds it (takes it home, answers for
        # it), not whoever drives this trip: the driver is the trip's operator.
        for batch in self:
            batch.driver_id = batch.operator_id.partner_id

    @api.depends(
        "state",
        "date_departure",
        "date_return",
        "picking_type_id.dispatch_management",
    )
    def _compute_trip_state(self):
        for batch in self:
            if not (batch.has_dispatch_management or batch.date_departure):
                batch.trip_state = False
            elif batch.state == "done" and not batch.date_departure:
                # Done before trips existed, or done without leaving: not a trip.
                batch.trip_state = False
            elif batch.state == "cancel":
                batch.trip_state = "cancelled"
            elif batch.date_return:
                batch.trip_state = "closed"
            elif batch.date_departure:
                batch.trip_state = "in_transit"
            else:
                batch.trip_state = "planned"

    @api.depends("picking_ids.state")
    def _compute_trip_counts(self):
        for batch in self:
            states = batch.picking_ids.mapped("state")
            batch.trip_delivered_count = states.count("done")
            batch.trip_pending_count = len(
                [state for state in states if state not in ("done", "cancel")]
            )

    @api.constrains(
        "odometer_departure", "odometer_return", "date_departure", "date_return"
    )
    def _check_trip_readings_order(self):
        for batch in self:
            if (
                batch.odometer_departure
                and batch.odometer_return
                and batch.odometer_return < batch.odometer_departure
            ):
                raise ValidationError(
                    self.env._(
                        "The odometer at return (%(end)s) cannot be lower than the "
                        "odometer at departure (%(start)s) on trip %(batch)s.",
                        end=batch.odometer_return,
                        start=batch.odometer_departure,
                        batch=batch.name,
                    )
                )
            if (
                batch.date_departure
                and batch.date_return
                and batch.date_return < batch.date_departure
            ):
                raise ValidationError(
                    self.env._(
                        "The return cannot be earlier than the departure on trip "
                        "%(batch)s.",
                        batch=batch.name,
                    )
                )

    def write(self, vals):
        self._check_trip_frozen_fields(vals)
        carried = {
            batch: batch.picking_ids for batch in self.filtered("date_departure")
        }
        res = super().write(vals)
        if "picking_ids" in vals:
            for batch, before in carried.items():
                batch._check_trip_takes_no_new_pickings(batch.picking_ids - before)
        return res

    @api.ondelete(at_uninstall=False)
    def _unlink_except_departed_trip(self):
        # A departed trip is the dispatch record; deleting it, or merging it into
        # another batch, would drop that record and orphan its ledger reading.
        departed = self.filtered("date_departure")
        if departed:
            raise UserError(
                self.env._(
                    "Trip %s has already left and cannot be deleted or merged.",
                    ", ".join(departed.mapped("name")),
                )
            )

    def _check_trip_takes_no_new_pickings(self, added):
        """Refuse transfers added to a trip after it left: it carries what it loaded."""
        if added:
            raise UserError(
                self.env._(
                    "Trip %(batch)s has already left; %(pickings)s cannot be added "
                    "to it. Put them on the next trip.",
                    batch=self.name,
                    pickings=", ".join(added.mapped("name")),
                )
            )

    def _check_trip_frozen_fields(self, vals):
        """Refuse edits to what a departed or closed trip already recorded."""
        departed = self.filtered("date_departure")
        frozen = [name for name in FROZEN_AT_DEPARTURE if name in vals]
        changed = departed.filtered(
            lambda batch: any(
                batch._fields[name].convert_to_write(batch[name], batch) != vals[name]
                for name in frozen
            )
        )
        returned = self.filtered("date_return")
        frozen_return = [name for name in FROZEN_AT_RETURN if name in vals]
        changed |= returned.filtered(
            lambda batch: any(batch[name] != vals[name] for name in frozen_return)
        )
        if changed:
            raise UserError(
                self.env._(
                    "Trip %(batch)s has already left: its vehicle, crew and readings "
                    "are the dispatch record and can no longer change.",
                    batch=", ".join(changed.mapped("name")),
                )
            )

    # ------------------------------------------------------------------
    # Departure and return
    # ------------------------------------------------------------------
    def _trip_departure_missing(self):
        """What the trip still lacks before its vehicle may leave."""
        self.check_singleton()
        missing = []
        if not self.picking_ids:
            missing.append(self.env._("Transfers"))
        if not self.vehicle_id:
            missing.append(self.env._("Vehicle"))
        if not self.operator_id:
            missing.append(self.env._("Operator"))
        if not self.supervisor_id:
            missing.append(self.env._("Supervisor"))
        if not self.odometer_departure:
            missing.append(self.env._("Odometer at departure"))
        return missing

    def action_depart(self):
        """The vehicle leaves: stamp the departure and freeze the trip."""
        self.check_singleton()
        if self.date_departure:
            raise UserError(self.env._("Trip %s has already departed.", self.name))
        missing = self._trip_departure_missing()
        if missing:
            raise UserError(
                self.env._(
                    "Trip %(batch)s cannot depart, it is missing: %(fields)s.",
                    batch=self.name,
                    fields=", ".join(missing),
                )
            )
        if self.operator_id.user_id and self.env.user == self.operator_id.user_id:
            raise UserError(
                self.env._(
                    "Trip %(batch)s is dispatched by its supervisor or the office, "
                    "not by its operator.",
                    batch=self.name,
                )
            )
        if self.operator_id.user_id and self.supervisor_id == self.operator_id.user_id:
            raise UserError(
                self.env._(
                    "The supervisor who authorises the departure of trip %(batch)s "
                    "cannot be its operator.",
                    batch=self.name,
                )
            )
        not_ready = self.picking_ids.filtered(
            lambda picking: picking.state not in ("assigned", "done", "cancel")
        )
        if not_ready:
            raise UserError(
                self.env._(
                    "Trip %(batch)s cannot depart with transfers that are not ready: "
                    "%(pickings)s.",
                    batch=self.name,
                    pickings=", ".join(not_ready.mapped("name")),
                )
            )
        if self.state == "draft":
            self.action_confirm()
        _debug.lifecycle("trip_depart", batches=self)
        self.write(
            {"date_departure": fields.Datetime.now(), "departed_uid": self.env.uid}
        )
        self.message_post(
            body=self.env._(
                "Departed with %(vehicle)s, operator %(operator)s, odometer %(odometer)s.",
                vehicle=self.vehicle_id.display_name,
                operator=self.operator_id.display_name,
                odometer=self.odometer_departure,
            )
        )
        return True

    def action_return(self):
        """Close the trip: stamp the return and log the odometer on the vehicle."""
        self.check_singleton()
        if not self.date_departure:
            raise UserError(self.env._("Trip %s has not departed yet.", self.name))
        if self.date_return:
            raise UserError(self.env._("Trip %s is already closed.", self.name))
        if not self.odometer_return:
            raise UserError(self.env._("The odometer at return is not set."))
        _debug.lifecycle("trip_return", batches=self)
        self.write({"date_return": fields.Datetime.now()})
        try:
            with self.env.cr.savepoint():
                self._record_trip_odometer()
        except UserError as error:
            # The trip closes regardless: the ledger's quarrel with another reading
            # is for whoever keeps the ledger, and it is left on the trip's record.
            self.message_post(
                body=self.env._(
                    "The vehicle's ledger refused the return odometer: %(error)s",
                    error=error,
                )
            )
        self.message_post(
            body=self.env._(
                "Closed at odometer %(odometer)s: %(delivered)s delivered, "
                "%(pending)s pending.",
                odometer=self.odometer_return,
                delivered=self.trip_delivered_count,
                pending=self.trip_pending_count,
            )
        )
        return True

    def _record_trip_odometer(self):
        """Log the return odometer on the vehicle's ledger, once per trip.

        :return: the ledger line, empty when the reading does not advance the vehicle
        :rtype: recordset
        """
        self.check_singleton()
        # The reading is the system's, not the driver's: a driver may close a trip
        # without rights on the vehicle ledger.
        Log = self.env["resource.asset.log"].sudo()
        if not self.vehicle_id:
            return Log
        if self.odometer_return <= self.vehicle_id.odometer:
            self.message_post(
                body=self.env._(
                    "The odometer at return (%(trip)s) does not advance the vehicle's "
                    "last reading (%(vehicle)s); the ledger keeps its own.",
                    trip=self.odometer_return,
                    vehicle=self.vehicle_id.odometer,
                )
            )
            return Log
        vals = {
            "date": self.date_return.date(),
            "odometer": self.odometer_return,
        }
        existing = Log.search([("picking_batch_id", "=", self.id)], limit=1)
        if existing:
            existing.write(vals)
            return existing
        return Log.create(
            {
                **vals,
                "asset_id": self.vehicle_id.id,
                "picking_batch_id": self.id,
                "source": "delivery",
                "state": "done",
                "notes": self.env._(
                    "Return odometer of trip %(batch)s.", batch=self.name
                ),
            }
        )

    def action_open_trip_driver_form(self):
        """Open the trip on the driver's own form."""
        self.check_singleton()
        return {
            "type": "ir.actions.act_window",
            "res_model": "stock.picking.batch",
            "res_id": self.id,
            "view_mode": "form",
            "view_id": self.env.ref("stock_fleet.stock_picking_batch_form_driver").id,
            "target": "current",
        }

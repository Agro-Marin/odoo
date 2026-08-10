"""Concrete consumer of ``resource.scheduling.mixin`` used by the tests.

The scheduling mixin only provides the reservation linkage and lifecycle; the
scheduling columns themselves live on the consumer.  Exercising it therefore
needs a real consumer model, and this addon is where such a model belongs.

It used to be declared inline in ``resource``'s own test files and pushed into
the registry with ``add_to_registry`` at ``setUpClass`` time.  That leaked: the
class stayed in the registry for the rest of the process while its table was
rolled back with the test transaction, so any later ORM trigger that scans
models with a ``resource_id`` field hit ``UndefinedTable`` — which is how three
unrelated ``hr_holidays`` accrual tests started failing whenever they ran in the
same session as the resource suite.
"""

from odoo import api, fields, models


class ResourceSchedulingTest(models.Model):
    _name = "resource.scheduling.test"
    _description = "Scheduling Mixin Test Model"
    # The allocation mixin, so the suite covers both halves: it inherits the
    # scheduling one, and the tests assert on ``allocated_hours`` /
    # ``allocated_percentage`` as well as on the projection lifecycle.
    _inherit = ["resource.allocation.mixin"]

    name = fields.Char()
    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)
    date_start = fields.Datetime("Scheduled Start", index=True)
    date_end = fields.Datetime("Scheduled End", index=True)
    resource_id = fields.Many2one("resource.resource", "Resource", index=True)
    resource_calendar_id = fields.Many2one(
        "resource.calendar",
        "Working Calendar",
        compute="_compute_resource_calendar_id",
        store=True,
        readonly=False,
    )

    _resource_schedule_idx = models.Index("(resource_id, date_start, date_end)")

    @api.depends("resource_id", "resource_id.calendar_id")
    def _compute_resource_calendar_id(self):
        for record in self:
            if record.resource_id and record.resource_id.calendar_id:
                record.resource_calendar_id = record.resource_id.calendar_id
            elif record.company_id:
                record.resource_calendar_id = record.company_id.resource_calendar_id
            else:
                record.resource_calendar_id = record.env.company.resource_calendar_id

    def _get_reservation_date_fields(self):
        return ("date_start", "date_end")

    def _get_reservation_vals_list(self):
        # Faithful consumer: project the local scheduling columns into a single
        # reservation so the mixin's create/write sync path and the
        # reservation-ledger aggregation of ``allocated_hours`` /
        # ``schedule_overlap_count`` are exercised end-to-end (rather than
        # re-implementing that logic inside the test model).
        self.ensure_one()
        if not self.date_start or not self.date_end:
            return []
        return [
            {
                "name": self.name or "Reservation",
                "date_start": self.date_start,
                "date_end": self.date_end,
                "resource_id": self.resource_id.id or False,
                "allocated_percentage": self.allocated_percentage or 100.0,
                "enforcement_mode": "soft",
            }
        ]

    def _get_sync_trigger_fields(self):
        # Re-sync the reservation when the resource or the allocation share
        # changes, not only the dates (the mixin default).
        return super()._get_sync_trigger_fields() | {
            "resource_id",
            "allocated_percentage",
        }


class ResourceSchedulingManualTest(models.Model):
    """A consumer that projects into the ledger on its own schedule.

    Prototype inheritance: same columns and same contract as the model above,
    with ``_reservation_sync_manual`` set.  It stands in for a consumer whose
    ``write`` keeps working after ``super()`` returns -- ``planning.slot`` is
    the real one -- for which projecting from inside the CRUD hooks reads
    half-settled state.
    """

    _name = "resource.scheduling.manual.test"
    _description = "Manual-Sync Scheduling Test Model"
    _inherit = ["resource.scheduling.test"]

    _reservation_sync_manual = True

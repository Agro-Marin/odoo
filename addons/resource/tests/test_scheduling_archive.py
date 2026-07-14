"""Regression tests for archive semantics of resource.scheduling.mixin.

Regression: editing a scheduling field on an *archived* consumer record re-ran
``_sync_reservations``, which searches only active reservations, found none
(they had been archived by the mirror), and therefore created a fresh **active**
reservation — a live claim on the resource for a record the user has archived.
The fix guards the sync to active records and reorders the archive mirror before
the sync so reactivation reconciles instead of duplicating.
"""

from datetime import datetime

import pytz

from odoo import api, fields, models
from odoo.models import add_to_registry
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

UTC = pytz.UTC


def _define_probe_model(cls):
    class SchedulingArchiveProbe(models.Model):
        _module = "resource"
        _name = cls.MODEL
        _description = "Scheduling Archive Probe"
        _inherit = ["resource.scheduling.mixin"]

        name = fields.Char()
        active = fields.Boolean(default=True)
        company_id = fields.Many2one(
            "res.company", default=lambda self: self.env.company
        )
        date_start = fields.Datetime()
        date_end = fields.Datetime()
        resource_id = fields.Many2one("resource.resource")
        resource_calendar_id = fields.Many2one(
            "resource.calendar",
            compute="_compute_resource_calendar_id",
            store=True,
            readonly=False,
        )

        @api.depends("resource_id", "resource_id.calendar_id")
        def _compute_resource_calendar_id(self):
            for rec in self:
                rec.resource_calendar_id = (
                    rec.resource_id.calendar_id
                    or rec.company_id.resource_calendar_id
                    or rec.env.company.resource_calendar_id
                )

        def _get_reservation_date_fields(self):
            return ("date_start", "date_end")

        def _get_reservation_vals_list(self):
            self.ensure_one()
            if not self.date_start or not self.date_end:
                return []
            return [
                {
                    "name": self.name or "R",
                    "date_start": self.date_start,
                    "date_end": self.date_end,
                    "resource_id": self.resource_id.id or False,
                    "allocated_percentage": 100.0,
                    "enforcement_mode": "soft",
                }
            ]

        def _get_sync_trigger_fields(self):
            return super()._get_sync_trigger_fields() | {"resource_id"}

    add_to_registry(cls.registry, SchedulingArchiveProbe)
    cls.registry._setup_models__(cls.env.cr, [])
    cls.registry.init_models(cls.env.cr, [cls.MODEL], {"module": "resource"})


@tagged("post_install", "-at_install")
class TestSchedulingMixinArchive(TransactionCase):
    MODEL = "resource.scheduling.archive.probe"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        _define_probe_model(cls)
        cls.calendar = cls.env["resource.calendar"].create(
            {"name": "Archive cal", "tz": "UTC"}
        )
        cls.resource = cls.env["resource.resource"].create(
            {"name": "Archive res", "calendar_id": cls.calendar.id, "tz": "UTC"}
        )
        cls.Model = cls.env[cls.MODEL]
        cls.Reservation = cls.env["resource.reservation"]

    def _res(self, rec, active_test=True):
        return (
            self.Reservation.with_context(active_test=active_test)
            .sudo()
            .search([("res_model", "=", self.MODEL), ("res_id", "=", rec.id)])
        )

    def _make(self):
        return self.Model.create(
            {
                "name": "Task",
                "date_start": datetime(2025, 1, 6, 8, 0),
                "date_end": datetime(2025, 1, 6, 17, 0),
                "resource_id": self.resource.id,
            }
        )

    def test_archive_then_edit_creates_no_active_reservation(self):
        """The confirmed bug: editing a trigger field while archived."""
        rec = self._make()
        self.assertEqual(len(self._res(rec)), 1)

        rec.active = False
        self.assertEqual(len(self._res(rec)), 0, "archive must leave no active res")

        rec.date_start = datetime(2025, 1, 6, 9, 0)
        self.assertEqual(
            len(self._res(rec)),
            0,
            "editing an archived record must not create an active reservation",
        )
        # The (single) reservation still exists, archived.
        self.assertEqual(len(self._res(rec, active_test=False)), 1)

    def test_unarchive_and_edit_does_not_duplicate(self):
        """Reactivating + editing in one write must reconcile, not duplicate."""
        rec = self._make()
        rec.active = False
        rec.write({"active": True, "date_start": datetime(2025, 1, 6, 10, 0)})

        active = self._res(rec)
        self.assertEqual(len(active), 1, "must reuse the reservation, not duplicate")
        self.assertEqual(active.date_start, datetime(2025, 1, 6, 10, 0))
        # No archived leftovers either.
        self.assertEqual(len(self._res(rec, active_test=False)), 1)

    def test_archive_then_unlink_leaves_no_reservation_rows(self):
        """Archive → delete (the common cleanup flow) must not orphan rows."""
        rec = self._make()
        rec.active = False
        self.assertEqual(len(self._res(rec, active_test=False)), 1)

        rec_id = rec.id
        rec.unlink()
        leftovers = (
            self.Reservation.with_context(active_test=False)
            .sudo()
            .search([("res_model", "=", self.MODEL), ("res_id", "=", rec_id)])
        )
        self.assertFalse(leftovers, "unlink must also purge archived reservations")

    def test_create_archived_record_plants_no_claim(self):
        """A record created already archived must not create reservations."""
        rec = self.Model.create(
            {
                "name": "Born archived",
                "active": False,
                "date_start": datetime(2025, 1, 6, 8, 0),
                "date_end": datetime(2025, 1, 6, 17, 0),
                "resource_id": self.resource.id,
            }
        )
        self.assertFalse(self._res(rec, active_test=False))

    def test_sync_reconciles_manually_archived_reservation(self):
        """A hand-archived mirror row is reconciled, not duplicated.

        If the sync were blind to archived rows, editing the consumer would
        create an active duplicate next to the archived twin — and the next
        unarchive cycle would turn both into live claims on the resource.
        """
        rec = self._make()
        self._res(rec).action_archive()

        rec.date_start = datetime(2025, 1, 6, 10, 0)
        rows = self._res(rec, active_test=False)
        self.assertEqual(len(rows), 1, "must reuse the archived row, not duplicate")
        self.assertTrue(rows.active, "engine-owned rows come back alive on sync")
        self.assertEqual(rows.date_start, datetime(2025, 1, 6, 10, 0))

    def test_sync_skips_noop_writes(self):
        """Re-syncing unchanged data must not rewrite the reservation."""
        rec = self._make()
        reservation = self._res(rec)
        # Backdate write_date so an (unwanted) write would be detectable.
        self.env.cr.execute(
            "UPDATE resource_reservation SET write_date = write_date"
            " - interval '1 hour' WHERE id = %s",
            [reservation.id],
        )
        reservation.invalidate_recordset(["write_date"])
        before = reservation.write_date

        rec._sync_reservations()  # same vals — reconcile must be a no-op
        reservation.invalidate_recordset(["write_date"])
        self.assertEqual(
            reservation.write_date,
            before,
            "unchanged reservation must not be rewritten on re-sync",
        )

    def test_aggregates_follow_archive_state(self):
        """Archiving flips reservations inactive → aggregates must follow.

        ``reservation_ids`` drops archived rows on read, but without an
        ``active`` dependency the stored sums kept their pre-archive values.
        """
        rec = self._make()
        self.assertGreater(rec.allocated_hours, 0.0)

        rec.active = False
        self.assertEqual(
            rec.allocated_hours,
            0.0,
            "an archived record's reservations are no longer commitments",
        )

        rec.active = True
        self.assertGreater(
            rec.allocated_hours, 0.0, "restore must revive the committed hours"
        )

    def test_unarchive_refreshes_edits_made_while_archived(self):
        """Edit while archived, then unarchive alone → reservation reflects the edit."""
        rec = self._make()
        rec.active = False
        rec.date_start = datetime(2025, 1, 6, 11, 0)  # edited while archived
        rec.active = True  # plain reactivation

        active = self._res(rec)
        self.assertEqual(len(active), 1)
        self.assertEqual(
            active.date_start,
            datetime(2025, 1, 6, 11, 0),
            "reactivation must resync the edit made while archived",
        )


@tagged("post_install", "-at_install")
class TestAdjustToCalendarMultiTz(TransactionCase):
    """Guard: batched ``_adjust_to_calendar`` must equal per-resource results.

    ``_adjust_to_calendar`` reuses its ``start``/``end`` locals across the
    per-resource loop; this only stays correct because ``astimezone`` preserves
    the instant.  This guards against a future refactor breaking that.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.calendar = cls.env["resource.calendar"].create(
            {"name": "MultiTz cal", "tz": "UTC"}
        )
        cls.r_brussels = cls.env["resource.resource"].create(
            {"name": "BR", "calendar_id": cls.calendar.id, "tz": "Europe/Brussels"}
        )
        cls.r_ny = cls.env["resource.resource"].create(
            {"name": "NY", "calendar_id": cls.calendar.id, "tz": "America/New_York"}
        )

    def test_batch_matches_per_resource(self):
        start = datetime(2025, 1, 6, 9, 0, tzinfo=UTC)
        end = datetime(2025, 1, 6, 18, 0, tzinfo=UTC)
        both = (self.r_brussels | self.r_ny)._adjust_to_calendar(start, end)
        both_rev = (self.r_ny | self.r_brussels)._adjust_to_calendar(start, end)
        only_br = self.r_brussels._adjust_to_calendar(start, end)
        only_ny = self.r_ny._adjust_to_calendar(start, end)
        self.assertEqual(both[self.r_brussels], only_br[self.r_brussels])
        self.assertEqual(both[self.r_ny], only_ny[self.r_ny])
        self.assertEqual(both_rev[self.r_brussels], only_br[self.r_brussels])
        self.assertEqual(both_rev[self.r_ny], only_ny[self.r_ny])

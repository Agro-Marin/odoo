"""Tests for resource.reservation model."""

from datetime import datetime

from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestResourceReservation(TransactionCase):
    """Test reservation creation, overlap detection, enforcement, and sync.

    Reference dates (2025):
        Mon 2025-01-06  |  Tue 2025-01-07  |  Wed 2025-01-08
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Reservation = cls.env["resource.reservation"]

        cls.calendar = cls.env["resource.calendar"].create(
            {"name": "Test Calendar", "tz": "UTC"}
        )
        cls.resource_a = cls.env["resource.resource"].create(
            {
                "name": "Resource A",
                "calendar_id": cls.calendar.id,
                "resource_type": "user",
            }
        )
        cls.resource_b = cls.env["resource.resource"].create(
            {
                "name": "Resource B",
                "calendar_id": cls.calendar.id,
                "resource_type": "material",
            }
        )

    # ------------------------------------------------------------------
    # Basic CRUD and computed fields
    # ------------------------------------------------------------------

    def test_create_reservation(self):
        """Creating a reservation computes allocated_hours from the calendar."""
        res = self.Reservation.create(
            {
                "name": "Test reservation",
                "resource_id": self.resource_a.id,
                "date_start": datetime(2025, 1, 6, 8, 0),  # Mon 08:00
                "date_end": datetime(2025, 1, 6, 17, 0),  # Mon 17:00
            }
        )
        expected = self.calendar.get_work_hours_count(
            datetime(2025, 1, 6, 8, 0), datetime(2025, 1, 6, 17, 0)
        )
        # Calendar-aware (lunch excluded) → strictly less than the 9h raw span.
        self.assertLess(res.allocated_hours, 9.0)
        self.assertAlmostEqual(res.allocated_hours, expected, places=2)
        self.assertEqual(res.allocated_percentage, 100.0)
        self.assertEqual(res.enforcement_mode, "soft")
        self.assertTrue(res.active)

    def test_no_resource_reservation(self):
        """Reservation without resource should still work (no overlap detection)."""
        res = self.Reservation.create(
            {
                "name": "Unassigned",
                "date_start": datetime(2025, 1, 6, 8, 0),
                "date_end": datetime(2025, 1, 6, 12, 0),
            }
        )
        self.assertEqual(res.schedule_overlap_count, 0)

    # ------------------------------------------------------------------
    # Date sanity constraint
    # ------------------------------------------------------------------

    def test_date_sanity_start_after_end(self):
        """Start >= end should raise ValidationError."""
        with self.assertRaises(ValidationError):
            self.Reservation.create(
                {
                    "name": "Bad dates",
                    "resource_id": self.resource_a.id,
                    "date_start": datetime(2025, 1, 6, 17, 0),
                    "date_end": datetime(2025, 1, 6, 8, 0),
                }
            )

    def test_date_sanity_equal_dates_allowed(self):
        """Start == end is allowed (zero-duration reservation, e.g. instant completion)."""
        res = self.Reservation.create(
            {
                "name": "Zero duration",
                "resource_id": self.resource_a.id,
                "date_start": datetime(2025, 1, 6, 8, 0),
                "date_end": datetime(2025, 1, 6, 8, 0),
            }
        )
        self.assertTrue(res.id)

    # ------------------------------------------------------------------
    # Overlap detection (soft mode — warning only)
    # ------------------------------------------------------------------

    def test_soft_overlap_100_percent(self):
        """Two 100% reservations on same resource overlap → count > 0."""
        res1 = self.Reservation.create(
            {
                "name": "Res 1",
                "resource_id": self.resource_a.id,
                "date_start": datetime(2025, 1, 6, 8, 0),
                "date_end": datetime(2025, 1, 6, 12, 0),
                "enforcement_mode": "soft",
            }
        )
        res2 = self.Reservation.create(
            {
                "name": "Res 2",
                "resource_id": self.resource_a.id,
                "date_start": datetime(2025, 1, 6, 10, 0),
                "date_end": datetime(2025, 1, 6, 14, 0),
                "enforcement_mode": "soft",
            }
        )
        # Invalidate cache to force recompute
        res1.invalidate_recordset(["schedule_overlap_count"])
        res2.invalidate_recordset(["schedule_overlap_count"])
        self.assertGreater(res1.schedule_overlap_count, 0, "100%+100% should overlap")
        self.assertGreater(res2.schedule_overlap_count, 0)

    def test_no_overlap_50_percent(self):
        """Two 50% reservations on same resource → no overlap (sum <= 100)."""
        res1 = self.Reservation.create(
            {
                "name": "Half 1",
                "resource_id": self.resource_a.id,
                "date_start": datetime(2025, 1, 6, 8, 0),
                "date_end": datetime(2025, 1, 6, 12, 0),
                "allocated_percentage": 50.0,
            }
        )
        res2 = self.Reservation.create(
            {
                "name": "Half 2",
                "resource_id": self.resource_a.id,
                "date_start": datetime(2025, 1, 6, 8, 0),
                "date_end": datetime(2025, 1, 6, 12, 0),
                "allocated_percentage": 50.0,
            }
        )
        res1.invalidate_recordset(["schedule_overlap_count"])
        res2.invalidate_recordset(["schedule_overlap_count"])
        self.assertEqual(res1.schedule_overlap_count, 0, "50%+50% should not overlap")
        self.assertEqual(res2.schedule_overlap_count, 0)

    def test_no_overlap_different_resources(self):
        """Overlapping times on different resources → no conflict."""
        res1 = self.Reservation.create(
            {
                "name": "On A",
                "resource_id": self.resource_a.id,
                "date_start": datetime(2025, 1, 6, 8, 0),
                "date_end": datetime(2025, 1, 6, 12, 0),
            }
        )
        res2 = self.Reservation.create(
            {
                "name": "On B",
                "resource_id": self.resource_b.id,
                "date_start": datetime(2025, 1, 6, 8, 0),
                "date_end": datetime(2025, 1, 6, 12, 0),
            }
        )
        res1.invalidate_recordset(["schedule_overlap_count"])
        self.assertEqual(res1.schedule_overlap_count, 0)
        res2.invalidate_recordset(["schedule_overlap_count"])
        self.assertEqual(res2.schedule_overlap_count, 0)

    def test_no_overlap_adjacent(self):
        """Adjacent reservations (end1 == start2) → no overlap."""
        res1 = self.Reservation.create(
            {
                "name": "Morning",
                "resource_id": self.resource_a.id,
                "date_start": datetime(2025, 1, 6, 8, 0),
                "date_end": datetime(2025, 1, 6, 12, 0),
            }
        )
        self.Reservation.create(
            {
                "name": "Afternoon",
                "resource_id": self.resource_a.id,
                "date_start": datetime(2025, 1, 6, 12, 0),
                "date_end": datetime(2025, 1, 6, 17, 0),
            }
        )
        res1.invalidate_recordset(["schedule_overlap_count"])
        self.assertEqual(res1.schedule_overlap_count, 0, "Adjacent should not overlap")

    # ------------------------------------------------------------------
    # Hard enforcement
    # ------------------------------------------------------------------

    def test_hard_enforcement_blocks_overlap(self):
        """Hard mode raises ValidationError when overlapping."""
        self.Reservation.create(
            {
                "name": "Existing hard",
                "resource_id": self.resource_a.id,
                "date_start": datetime(2025, 1, 6, 8, 0),
                "date_end": datetime(2025, 1, 6, 12, 0),
                "enforcement_mode": "hard",
            }
        )
        with self.assertRaises(ValidationError):
            self.Reservation.create(
                {
                    "name": "Conflicting hard",
                    "resource_id": self.resource_a.id,
                    "date_start": datetime(2025, 1, 6, 10, 0),
                    "date_end": datetime(2025, 1, 6, 14, 0),
                    "enforcement_mode": "hard",
                }
            )

    def test_hard_enforcement_allows_50_percent(self):
        """Hard mode allows two 50% reservations (sum <= 100)."""
        self.Reservation.create(
            {
                "name": "Hard half 1",
                "resource_id": self.resource_a.id,
                "date_start": datetime(2025, 1, 6, 8, 0),
                "date_end": datetime(2025, 1, 6, 12, 0),
                "allocated_percentage": 50.0,
                "enforcement_mode": "hard",
            }
        )
        # Should NOT raise
        res2 = self.Reservation.create(
            {
                "name": "Hard half 2",
                "resource_id": self.resource_a.id,
                "date_start": datetime(2025, 1, 6, 8, 0),
                "date_end": datetime(2025, 1, 6, 12, 0),
                "allocated_percentage": 50.0,
                "enforcement_mode": "hard",
            }
        )
        self.assertTrue(res2.id, "50%+50% hard should be allowed")
        res2.invalidate_recordset(["schedule_overlap_count"])
        self.assertEqual(
            res2.schedule_overlap_count, 0, "50%+50% must not be a conflict"
        )

    # ------------------------------------------------------------------
    # Archived reservations must not count as conflicts
    # ------------------------------------------------------------------

    def test_archived_reservation_not_a_conflict(self):
        """An archived (active=False) reservation is no longer a claim on the
        resource: it must not be counted as an overlap by an active one."""
        res1 = self.Reservation.create(
            {
                "name": "Active",
                "resource_id": self.resource_a.id,
                "date_start": datetime(2025, 1, 6, 8, 0),
                "date_end": datetime(2025, 1, 6, 12, 0),
            }
        )
        res2 = self.Reservation.create(
            {
                "name": "To be archived",
                "resource_id": self.resource_a.id,
                "date_start": datetime(2025, 1, 6, 9, 0),
                "date_end": datetime(2025, 1, 6, 11, 0),
            }
        )
        self.env.invalidate_all()
        self.assertGreater(res1.schedule_overlap_count, 0, "both active → conflict")

        res2.active = False
        self.env.invalidate_all()
        self.assertEqual(
            res1.schedule_overlap_count,
            0,
            "archived reservation must not be counted as a conflict",
        )
        self.assertEqual(res2.schedule_overlap_count, 0)

    def test_hard_enforcement_ignores_archived(self):
        """A hard reservation must not be blocked by an archived overlap."""
        blocker = self.Reservation.create(
            {
                "name": "Archived blocker",
                "resource_id": self.resource_a.id,
                "date_start": datetime(2025, 1, 6, 8, 0),
                "date_end": datetime(2025, 1, 6, 12, 0),
                "enforcement_mode": "hard",
            }
        )
        blocker.active = False
        # Should NOT raise now that the overlapping reservation is archived.
        res = self.Reservation.create(
            {
                "name": "New hard",
                "resource_id": self.resource_a.id,
                "date_start": datetime(2025, 1, 6, 10, 0),
                "date_end": datetime(2025, 1, 6, 14, 0),
                "enforcement_mode": "hard",
            }
        )
        self.assertTrue(res.id)

    # ------------------------------------------------------------------
    # Cross-origin overlap detection
    # ------------------------------------------------------------------

    def test_cross_origin_overlap(self):
        """Reservations from different source models on same resource overlap."""
        res1 = self.Reservation.create(
            {
                "name": "From tasks",
                "resource_id": self.resource_a.id,
                "date_start": datetime(2025, 1, 6, 8, 0),
                "date_end": datetime(2025, 1, 6, 12, 0),
                "res_model": "project.task",
                "res_id": 1,
            }
        )
        res2 = self.Reservation.create(
            {
                "name": "From rooms",
                "resource_id": self.resource_a.id,
                "date_start": datetime(2025, 1, 6, 10, 0),
                "date_end": datetime(2025, 1, 6, 14, 0),
                "res_model": "room.booking",
                "res_id": 1,
            }
        )
        res1.invalidate_recordset(["schedule_overlap_count"])
        res2.invalidate_recordset(["schedule_overlap_count"])
        self.assertGreater(
            res1.schedule_overlap_count,
            0,
            "Cross-origin overlap should be detected",
        )

    # ------------------------------------------------------------------
    # _sync_reservation helper
    # ------------------------------------------------------------------

    def test_sync_reservation_create(self):
        """_sync_reservation creates reservations for a consumer record."""
        # Use a partner as a stand-in consumer (any saved record works)
        partner = self.env["res.partner"].create({"name": "Test Consumer"})
        result = self.Reservation._sync_reservation(
            partner,
            [
                {
                    "name": "Synced reservation",
                    "date_start": datetime(2025, 1, 6, 8, 0),
                    "date_end": datetime(2025, 1, 6, 12, 0),
                    "resource_id": self.resource_a.id,
                    "allocated_percentage": 100.0,
                    "enforcement_mode": "soft",
                },
            ],
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result.res_model, "res.partner")
        self.assertEqual(result.res_id, partner.id)

    def test_sync_reservation_delete_all(self):
        """_sync_reservation with empty list deletes all reservations."""
        partner = self.env["res.partner"].create({"name": "Consumer 2"})
        self.Reservation._sync_reservation(
            partner,
            [
                {
                    "name": "To delete",
                    "date_start": datetime(2025, 1, 6, 8, 0),
                    "date_end": datetime(2025, 1, 6, 12, 0),
                    "resource_id": self.resource_a.id,
                    "allocated_percentage": 100.0,
                    "enforcement_mode": "soft",
                },
            ],
        )
        # Now sync with empty list
        result = self.Reservation._sync_reservation(partner, [])
        self.assertEqual(len(result), 0)
        remaining = self.Reservation.search(
            [("res_model", "=", "res.partner"), ("res_id", "=", partner.id)]
        )
        self.assertEqual(len(remaining), 0)

    def test_sync_reservation_reconcile(self):
        """_sync_reservation updates existing and creates new."""
        partner = self.env["res.partner"].create({"name": "Consumer 3"})
        # Initial sync: one reservation on resource_a
        self.Reservation._sync_reservation(
            partner,
            [
                {
                    "name": "On A",
                    "date_start": datetime(2025, 1, 6, 8, 0),
                    "date_end": datetime(2025, 1, 6, 12, 0),
                    "resource_id": self.resource_a.id,
                    "allocated_percentage": 100.0,
                    "enforcement_mode": "soft",
                },
            ],
        )
        # Re-sync: change to resource_b
        result = self.Reservation._sync_reservation(
            partner,
            [
                {
                    "name": "On B now",
                    "date_start": datetime(2025, 1, 7, 8, 0),
                    "date_end": datetime(2025, 1, 7, 12, 0),
                    "resource_id": self.resource_b.id,
                    "allocated_percentage": 100.0,
                    "enforcement_mode": "soft",
                },
            ],
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result.resource_id, self.resource_b)
        # Old reservation on resource_a should be deleted
        old = self.Reservation.search(
            [
                ("res_model", "=", "res.partner"),
                ("res_id", "=", partner.id),
                ("resource_id", "=", self.resource_a.id),
            ]
        )
        self.assertEqual(len(old), 0)

    def test_sync_reservation_reconciles_duplicate_resource(self):
        """Several existing reservations sharing one resource must all be
        reconciled: the surplus ones are deleted, never left orphaned.

        Regression: keying ``existing`` by a single record per resource_id
        hid duplicates, so they were neither updated nor deleted and lingered
        as phantom conflicts on the resource.
        """
        partner = self.env["res.partner"].create({"name": "Dup Consumer"})
        # Seed two reservations sharing resource_a, bypassing the sync helper.
        self.Reservation.create(
            [
                {
                    "name": f"Dup {i}",
                    "res_model": "res.partner",
                    "res_id": partner.id,
                    "resource_id": self.resource_a.id,
                    "date_start": datetime(2025, 1, 6, 8, 0),
                    "date_end": datetime(2025, 1, 6, 12, 0),
                }
                for i in range(2)
            ]
        )
        result = self.Reservation._sync_reservation(
            partner,
            [
                {
                    "name": "Only one",
                    "date_start": datetime(2025, 1, 7, 8, 0),
                    "date_end": datetime(2025, 1, 7, 12, 0),
                    "resource_id": self.resource_a.id,
                    "allocated_percentage": 100.0,
                    "enforcement_mode": "soft",
                },
            ],
        )
        self.assertEqual(len(result), 1)
        remaining = self.Reservation.search(
            [("res_model", "=", "res.partner"), ("res_id", "=", partner.id)]
        )
        self.assertEqual(
            len(remaining),
            1,
            "surplus duplicate reservation must be deleted, not orphaned",
        )

    def test_calendar_recomputes_on_company_change(self):
        """For a resourceless reservation the calendar follows ``company_id``;
        changing the company must recompute it (regression: ``company_id`` was
        missing from the compute's dependencies)."""
        company_b = self.env["res.company"].create({"name": "Reservation Co B"})
        self.assertNotEqual(
            self.env.company.resource_calendar_id,
            company_b.resource_calendar_id,
            "each company should get its own default calendar",
        )
        res = self.Reservation.create(
            {
                "name": "Company-scoped",
                "date_start": datetime(2025, 1, 6, 8, 0),
                "date_end": datetime(2025, 1, 6, 12, 0),
                "company_id": self.env.company.id,
            }
        )
        self.assertEqual(
            res.resource_calendar_id, self.env.company.resource_calendar_id
        )
        res.company_id = company_b
        self.assertEqual(
            res.resource_calendar_id,
            company_b.resource_calendar_id,
            "calendar must recompute when the company changes",
        )

    # ------------------------------------------------------------------
    # Cumulative (N-way) overlap detection
    # ------------------------------------------------------------------

    def test_cumulative_overlap_three_partial(self):
        """Three 50% reservations overlapping at the same instant sum to 150%
        — each must report the other two as conflicts, even though no single
        *pair* exceeds 100%."""
        reservations = self.Reservation.create(
            [
                {
                    "name": f"Third {i}",
                    "resource_id": self.resource_a.id,
                    "date_start": datetime(2025, 1, 6, 8, 0),
                    "date_end": datetime(2025, 1, 6, 12, 0),
                    "allocated_percentage": 50.0,
                }
                for i in range(3)
            ]
        )
        self.env.invalidate_all()
        for res in reservations:
            self.assertEqual(
                res.schedule_overlap_count,
                2,
                "each of 3×50% must see the other two as cumulative conflicts",
            )

    def test_cumulative_overlap_below_100_no_conflict(self):
        """Three 30% reservations sum to 90% ≤ 100% → no conflict."""
        reservations = self.Reservation.create(
            [
                {
                    "name": f"Small {i}",
                    "resource_id": self.resource_a.id,
                    "date_start": datetime(2025, 1, 6, 8, 0),
                    "date_end": datetime(2025, 1, 6, 12, 0),
                    "allocated_percentage": 30.0,
                }
                for i in range(3)
            ]
        )
        self.env.invalidate_all()
        for res in reservations:
            self.assertEqual(res.schedule_overlap_count, 0)

    def test_cumulative_overlap_partial_time_window(self):
        """Cumulative over-allocation is detected only for reservations that
        share the over-100% instant, not merely the same resource."""
        # A 08-12 @60%, B 10-14 @60% (overlap 10-12 → 120%), C 14-16 @60%
        # (starts exactly when B ends → never shares an over-100% instant).
        a, b, c = self.Reservation.create(
            [
                {
                    "name": "A",
                    "resource_id": self.resource_a.id,
                    "date_start": datetime(2025, 1, 6, 8, 0),
                    "date_end": datetime(2025, 1, 6, 12, 0),
                    "allocated_percentage": 60.0,
                },
                {
                    "name": "B",
                    "resource_id": self.resource_a.id,
                    "date_start": datetime(2025, 1, 6, 10, 0),
                    "date_end": datetime(2025, 1, 6, 14, 0),
                    "allocated_percentage": 60.0,
                },
                {
                    "name": "C",
                    "resource_id": self.resource_a.id,
                    "date_start": datetime(2025, 1, 6, 14, 0),
                    "date_end": datetime(2025, 1, 6, 16, 0),
                    "allocated_percentage": 60.0,
                },
            ]
        )
        self.env.invalidate_all()
        self.assertEqual(a.schedule_overlap_count, 1, "A conflicts with B only")
        self.assertEqual(b.schedule_overlap_count, 1, "B conflicts with A only")
        self.assertEqual(c.schedule_overlap_count, 0, "C never exceeds 100%")

    # ------------------------------------------------------------------
    # _reservation_intervals_batch
    # ------------------------------------------------------------------

    def test_reservation_intervals_batch(self):
        """Query occupied intervals for a resource."""
        from pytz import utc

        self.Reservation.create(
            {
                "name": "Interval test",
                "resource_id": self.resource_a.id,
                "date_start": datetime(2025, 1, 6, 8, 0),
                "date_end": datetime(2025, 1, 6, 12, 0),
            }
        )
        start_dt = datetime(2025, 1, 6, 0, 0, tzinfo=utc)
        end_dt = datetime(2025, 1, 7, 0, 0, tzinfo=utc)
        result = self.Reservation._reservation_intervals_batch(
            start_dt, end_dt, self.resource_a
        )
        self.assertIn(self.resource_a.id, result)
        intervals = list(result[self.resource_a.id])
        self.assertEqual(len(intervals), 1, "Should return one interval")

    def test_reservation_intervals_batch_empty(self):
        """No reservations → empty intervals for all requested resources."""
        from pytz import utc

        start_dt = datetime(2025, 1, 6, 0, 0, tzinfo=utc)
        end_dt = datetime(2025, 1, 7, 0, 0, tzinfo=utc)
        result = self.Reservation._reservation_intervals_batch(
            start_dt, end_dt, self.resource_a | self.resource_b
        )
        self.assertIn(self.resource_a.id, result)
        self.assertIn(self.resource_b.id, result)
        self.assertEqual(len(list(result[self.resource_a.id])), 0)
        self.assertEqual(len(list(result[self.resource_b.id])), 0)

    # ------------------------------------------------------------------
    # origin_display and action_open_origin
    # ------------------------------------------------------------------

    def test_origin_display(self):
        """origin_display resolves the source record's name."""
        partner = self.env["res.partner"].create({"name": "Display Test"})
        res = self.Reservation.create(
            {
                "name": "With origin",
                "resource_id": self.resource_a.id,
                "date_start": datetime(2025, 1, 6, 8, 0),
                "date_end": datetime(2025, 1, 6, 12, 0),
                "res_model": "res.partner",
                "res_id": partner.id,
            }
        )
        self.assertEqual(res.origin_display, "Display Test")

    def test_action_open_origin(self):
        """action_open_origin returns an act_window action."""
        partner = self.env["res.partner"].create({"name": "Action Test"})
        res = self.Reservation.create(
            {
                "name": "With action",
                "resource_id": self.resource_a.id,
                "date_start": datetime(2025, 1, 6, 8, 0),
                "date_end": datetime(2025, 1, 6, 12, 0),
                "res_model": "res.partner",
                "res_id": partner.id,
            }
        )
        action = res.action_open_origin()
        self.assertEqual(action["res_model"], "res.partner")
        self.assertEqual(action["res_id"], partner.id)

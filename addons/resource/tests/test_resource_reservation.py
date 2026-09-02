from datetime import UTC, datetime

from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestResourceReservation(TransactionCase):
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

    def test_create_reservation(self):
        res = self.Reservation.create(
            {
                "name": "Test reservation",
                "resource_id": self.resource_a.id,
                "date_start": datetime(2025, 1, 6, 8, 0),
                "date_end": datetime(2025, 1, 6, 17, 0),
            }
        )
        expected = self.calendar.get_work_hours_count(
            datetime(2025, 1, 6, 8, 0), datetime(2025, 1, 6, 17, 0)
        )
        self.assertLess(res.allocated_hours, 9.0)
        self.assertAlmostEqual(res.allocated_hours, expected, places=2)
        self.assertEqual(res.allocated_percentage, 100.0)
        self.assertEqual(res.enforcement_mode, "soft")
        self.assertTrue(res.active)

    def test_no_resource_reservation(self):
        res = self.Reservation.create(
            {
                "name": "Unassigned",
                "date_start": datetime(2025, 1, 6, 8, 0),
                "date_end": datetime(2025, 1, 6, 12, 0),
            }
        )
        self.assertEqual(res.schedule_overlap_count, 0)

    def test_date_sanity_start_after_end(self):
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
        res = self.Reservation.create(
            {
                "name": "Zero duration",
                "resource_id": self.resource_a.id,
                "date_start": datetime(2025, 1, 6, 8, 0),
                "date_end": datetime(2025, 1, 6, 8, 0),
            }
        )
        self.assertTrue(res.id)

    def test_soft_overlap_100_percent(self):
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
        res1.invalidate_recordset(["schedule_overlap_count"])
        res2.invalidate_recordset(["schedule_overlap_count"])
        self.assertGreater(res1.schedule_overlap_count, 0, "100%+100% should overlap")
        self.assertGreater(res2.schedule_overlap_count, 0)

    def test_no_overlap_50_percent(self):
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

    def test_hard_enforcement_blocks_overlap(self):
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

    def test_archived_reservation_not_a_conflict(self):
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

    def test_hard_enforcement_blocks_unarchive_into_conflict(self):
        blocker = self.Reservation.create(
            {
                "name": "Hard blocker",
                "resource_id": self.resource_a.id,
                "date_start": datetime(2025, 1, 6, 8, 0),
                "date_end": datetime(2025, 1, 6, 12, 0),
                "enforcement_mode": "hard",
            }
        )
        blocker.active = False
        self.Reservation.create(
            {
                "name": "Took the slot meanwhile",
                "resource_id": self.resource_a.id,
                "date_start": datetime(2025, 1, 6, 10, 0),
                "date_end": datetime(2025, 1, 6, 14, 0),
            }
        )
        with self.assertRaises(ValidationError):
            blocker.active = True

    def test_hard_enforcement_blocks_mode_switch_into_conflict(self):
        soft = self.Reservation.create(
            {
                "name": "Soft overlapper",
                "resource_id": self.resource_a.id,
                "date_start": datetime(2025, 1, 6, 8, 0),
                "date_end": datetime(2025, 1, 6, 12, 0),
            }
        )
        self.Reservation.create(
            {
                "name": "Other overlapper",
                "resource_id": self.resource_a.id,
                "date_start": datetime(2025, 1, 6, 10, 0),
                "date_end": datetime(2025, 1, 6, 14, 0),
            }
        )
        with self.assertRaises(ValidationError):
            soft.enforcement_mode = "hard"

    def test_cross_origin_overlap(self):
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

    def test_sync_reservation_create(self):
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
        result = self.Reservation._sync_reservation(partner, [])
        self.assertEqual(len(result), 0)
        remaining = self.Reservation.search(
            [("res_model", "=", "res.partner"), ("res_id", "=", partner.id)]
        )
        self.assertEqual(len(remaining), 0)

    def test_sync_reservation_reconcile(self):
        partner = self.env["res.partner"].create({"name": "Consumer 3"})
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
        old = self.Reservation.search(
            [
                ("res_model", "=", "res.partner"),
                ("res_id", "=", partner.id),
                ("resource_id", "=", self.resource_a.id),
            ]
        )
        self.assertEqual(len(old), 0)

    def test_sync_reservation_reconciles_duplicate_resource(self):
        partner = self.env["res.partner"].create({"name": "Dup Consumer"})
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

    def test_cumulative_overlap_three_partial(self):
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

    def test_reservation_intervals_batch(self):
        self.Reservation.create(
            {
                "name": "Interval test",
                "resource_id": self.resource_a.id,
                "date_start": datetime(2025, 1, 6, 8, 0),
                "date_end": datetime(2025, 1, 6, 12, 0),
            }
        )
        start_dt = datetime(2025, 1, 6, 0, 0, tzinfo=UTC)
        end_dt = datetime(2025, 1, 7, 0, 0, tzinfo=UTC)
        result = self.Reservation._reservation_intervals_batch(
            start_dt, end_dt, self.resource_a
        )
        self.assertIn(self.resource_a.id, result)
        intervals = list(result[self.resource_a.id])
        self.assertEqual(len(intervals), 1, "Should return one interval")

    def test_reservation_intervals_batch_empty(self):
        start_dt = datetime(2025, 1, 6, 0, 0, tzinfo=UTC)
        end_dt = datetime(2025, 1, 7, 0, 0, tzinfo=UTC)
        result = self.Reservation._reservation_intervals_batch(
            start_dt, end_dt, self.resource_a | self.resource_b
        )
        self.assertIn(self.resource_a.id, result)
        self.assertIn(self.resource_b.id, result)
        self.assertEqual(len(list(result[self.resource_a.id])), 0)
        self.assertEqual(len(list(result[self.resource_b.id])), 0)

    def test_origin_display(self):
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

    def test_action_view_origin(self):
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
        action = res.action_view_origin()
        self.assertEqual(action["res_model"], "res.partner")
        self.assertEqual(action["res_id"], partner.id)

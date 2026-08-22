from datetime import datetime

from odoo.exceptions import ValidationError
from odoo.tests import new_test_user, tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestSchedulingMixin(TransactionCase):
    """Test the resource scheduling mixin fields and methods.

    Uses a standard 40h/week calendar (Mon-Fri, 8:00-12:00 + 13:00-17:00 UTC)
    and various resource configurations to validate the consolidated scheduling
    logic.

    Reference dates (2025):
        Mon 2025-01-06  |  Tue 2025-01-07  |  Wed 2025-01-08
        Thu 2025-01-09  |  Fri 2025-01-10  |  Sat 2025-01-11
        Sun 2025-01-12  |  Mon 2025-01-13
    """

    MODEL_NAME = "resource.scheduling.test"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # Standard 40h/week calendar (Mon-Fri 8-12 + 13-17, UTC)
        cls.calendar = cls.env["resource.calendar"].create(
            {
                "name": "Test 40h Calendar",
                "tz": "UTC",
            }
        )

        # Regular resource using the standard calendar
        cls.resource = cls.env["resource.resource"].create(
            {
                "name": "Test Resource",
                "calendar_id": cls.calendar.id,
                "tz": "UTC",
            }
        )

        # Flexible resource (calendar with flexible_hours=True)
        cls.flex_calendar = cls.env["resource.calendar"].create(
            {
                "name": "Flexible 35h Calendar",
                "tz": "UTC",
                "flexible_hours": True,
                "hours_per_day": 7.0,
                "full_time_required_hours": 35,
            }
        )
        cls.flex_resource = cls.env["resource.resource"].create(
            {
                "name": "Flex Resource",
                "calendar_id": cls.flex_calendar.id,
                "tz": "UTC",
            }
        )

        # Fully flexible resource (no calendar at all)
        cls.fully_flex_resource = cls.env["resource.resource"].create(
            {
                "name": "Fully Flex Resource",
                "calendar_id": False,
                "tz": "UTC",
            }
        )

        cls.Model = cls.env[cls.MODEL_NAME]

    # ------------------------------------------------------------------
    # Allocated hours — calendar-aware computation
    # ------------------------------------------------------------------

    def test_allocated_hours_with_calendar(self):
        """Mon 8:00 → Mon 17:00 with standard calendar = 8h (excludes lunch)."""
        record = self.Model.create(
            {
                "name": "Single day",
                "date_start": datetime(2025, 1, 6, 8, 0),  # Mon 8:00
                "date_end": datetime(2025, 1, 6, 17, 0),  # Mon 17:00
                "resource_id": self.resource.id,
            }
        )
        self.assertEqual(record.allocated_hours, 8.0)

    def test_allocated_hours_cross_day(self):
        """Mon 8:00 → Tue 17:00 = 16h (two full work days)."""
        record = self.Model.create(
            {
                "name": "Cross day",
                "date_start": datetime(2025, 1, 6, 8, 0),  # Mon 8:00
                "date_end": datetime(2025, 1, 7, 17, 0),  # Tue 17:00
                "resource_id": self.resource.id,
            }
        )
        self.assertEqual(record.allocated_hours, 16.0)

    def test_allocated_hours_cross_weekend(self):
        """Fri 8:00 → Mon 17:00 = 16h (skips Sat + Sun)."""
        record = self.Model.create(
            {
                "name": "Cross weekend",
                "date_start": datetime(2025, 1, 10, 8, 0),  # Fri 8:00
                "date_end": datetime(2025, 1, 13, 17, 0),  # Mon 17:00
                "resource_id": self.resource.id,
            }
        )
        self.assertEqual(record.allocated_hours, 16.0)

    def test_allocated_hours_no_resource(self):
        """No resource → uses the company calendar (not a raw timedelta)."""
        record = self.Model.create(
            {
                "name": "No resource",
                "date_start": datetime(2025, 1, 6, 8, 0),  # Mon 8:00
                "date_end": datetime(2025, 1, 6, 17, 0),  # Mon 17:00
            }
        )
        self.assertFalse(record.resource_id)
        # The reservation falls back to the company calendar; assert against
        # its actual output rather than a hard-coded number so the test does
        # not depend on which default calendar the database ships with.
        expected = self.env.company.resource_calendar_id.get_work_hours_count(
            datetime(2025, 1, 6, 8, 0),
            datetime(2025, 1, 6, 17, 0),
        )
        # Calendar-aware (lunch excluded) → strictly less than the 9h raw span.
        self.assertLess(record.allocated_hours, 9.0)
        self.assertAlmostEqual(record.allocated_hours, expected, places=2)

    def test_allocated_hours_flexible_resource(self):
        """Flexible resource: work hours capped by flex calendar constraints."""
        record = self.Model.create(
            {
                "name": "Flexible",
                "date_start": datetime(2025, 1, 6, 0, 0),  # Mon 00:00
                "date_end": datetime(2025, 1, 10, 23, 59),  # Fri 23:59
                "resource_id": self.flex_resource.id,
            }
        )
        # 35h/week flex calendar across a full work week
        self.assertAlmostEqual(record.allocated_hours, 35.0, places=0)

    def test_allocated_percentage(self):
        """50% allocation of an 8h slot = 4h."""
        record = self.Model.create(
            {
                "name": "50% allocation",
                "date_start": datetime(2025, 1, 6, 8, 0),  # Mon 8:00
                "date_end": datetime(2025, 1, 6, 17, 0),  # Mon 17:00
                "resource_id": self.resource.id,
                "allocated_percentage": 50.0,
            }
        )
        self.assertEqual(record.allocated_hours, 4.0)

    # ------------------------------------------------------------------
    # Calendar snapping
    # ------------------------------------------------------------------

    def test_snap_to_calendar(self):
        """Midnight → should snap to first work interval (8:00)."""
        record = self.Model.create(
            {
                "name": "Snap test",
                "resource_id": self.resource.id,
            }
        )
        snapped_start, snapped_end = record._scheduling_snap_to_calendar(
            datetime(2025, 1, 6, 0, 0),  # Mon midnight
            datetime(2025, 1, 6, 23, 59),  # Mon 23:59
            calendar=self.calendar,
        )
        self.assertEqual(snapped_start.hour, 8)
        self.assertEqual(snapped_end.hour, 17)

    # ------------------------------------------------------------------
    # Plan hours (inverse computation)
    # ------------------------------------------------------------------

    def test_plan_hours(self):
        """16 working hours from Mon 8:00 → should end Tue 17:00."""
        record = self.Model.create(
            {
                "name": "Plan hours",
                "resource_id": self.resource.id,
            }
        )
        end = record._scheduling_plan_hours(
            16.0,
            datetime(2025, 1, 6, 8, 0),  # Mon 8:00
            resource=self.resource,
            calendar=self.calendar,
        )
        self.assertIsNotNone(end)
        # 8h Mon + 8h Tue = 16h → Tue 17:00
        self.assertEqual(end, datetime(2025, 1, 7, 17, 0))

    # ------------------------------------------------------------------
    # Overlap detection
    # ------------------------------------------------------------------

    def test_overlap_detection(self):
        """Two 100% slots on same resource at same time → conflict."""
        rec1 = self.Model.create(
            {
                "name": "Slot A",
                "date_start": datetime(2025, 1, 6, 8, 0),
                "date_end": datetime(2025, 1, 6, 17, 0),
                "resource_id": self.resource.id,
                "allocated_percentage": 100.0,
            }
        )
        rec2 = self.Model.create(
            {
                "name": "Slot B",
                "date_start": datetime(2025, 1, 6, 8, 0),
                "date_end": datetime(2025, 1, 6, 17, 0),
                "resource_id": self.resource.id,
                "allocated_percentage": 100.0,
            }
        )
        # Overlap counts are cross-record (a new reservation cannot invalidate
        # a sibling's cached count), so flush the whole env before reading.
        self.env.invalidate_all()
        self.assertGreater(rec1.schedule_overlap_count, 0)
        self.assertGreater(rec2.schedule_overlap_count, 0)

    def test_overlap_percentage(self):
        """Two 50% slots → no conflict; two 60% slots → conflict."""
        rec1 = self.Model.create(
            {
                "name": "Slot 50A",
                "date_start": datetime(2025, 1, 6, 8, 0),
                "date_end": datetime(2025, 1, 6, 17, 0),
                "resource_id": self.resource.id,
                "allocated_percentage": 50.0,
            }
        )
        rec2 = self.Model.create(
            {
                "name": "Slot 50B",
                "date_start": datetime(2025, 1, 6, 8, 0),
                "date_end": datetime(2025, 1, 6, 17, 0),
                "resource_id": self.resource.id,
                "allocated_percentage": 50.0,
            }
        )
        self.env.invalidate_all()
        # 50 + 50 = 100 → not > 100 → no conflict
        self.assertEqual(rec1.schedule_overlap_count, 0)
        self.assertEqual(rec2.schedule_overlap_count, 0)

        # Now bump to 60% each → 120% > 100 → conflict. The allocation change
        # re-syncs each reservation (see _get_fields_sync_trigger override).
        rec1.allocated_percentage = 60.0
        rec2.allocated_percentage = 60.0
        self.env.invalidate_all()
        self.assertGreater(rec1.schedule_overlap_count, 0)
        self.assertGreater(rec2.schedule_overlap_count, 0)

    def test_no_overlap_different_resource(self):
        """Same time, different resources → no conflict."""
        resource2 = self.env["resource.resource"].create(
            {
                "name": "Other Resource",
                "calendar_id": self.calendar.id,
                "tz": "UTC",
            }
        )
        rec1 = self.Model.create(
            {
                "name": "Resource 1 slot",
                "date_start": datetime(2025, 1, 6, 8, 0),
                "date_end": datetime(2025, 1, 6, 17, 0),
                "resource_id": self.resource.id,
                "allocated_percentage": 100.0,
            }
        )
        rec2 = self.Model.create(
            {
                "name": "Resource 2 slot",
                "date_start": datetime(2025, 1, 6, 8, 0),
                "date_end": datetime(2025, 1, 6, 17, 0),
                "resource_id": resource2.id,
                "allocated_percentage": 100.0,
            }
        )
        self.env.invalidate_all()
        self.assertEqual(rec1.schedule_overlap_count, 0)
        self.assertEqual(rec2.schedule_overlap_count, 0)

    # ------------------------------------------------------------------
    # Manual projection (_reservation_sync_manual)
    # ------------------------------------------------------------------

    def _manual_vals(self, **overrides):
        vals = {
            "name": "Manual",
            "date_start": datetime(2025, 1, 6, 8, 0),
            "date_end": datetime(2025, 1, 6, 17, 0),
            "resource_id": self.resource.id,
        }
        vals.update(overrides)
        return vals

    def test_manual_sync_skips_the_create_hook(self):
        """A manual-sync consumer books nothing until it says so."""
        Manual = self.env["resource.scheduling.manual.test"]
        record = Manual.create(self._manual_vals())
        self.assertFalse(
            record.reservation_ids,
            "create must not project for a consumer that manages its own sync",
        )

        record._sync_reservations()
        self.assertEqual(len(record.reservation_ids), 1)
        self.assertEqual(record.reservation_ids.date_start, datetime(2025, 1, 6, 8, 0))

    def test_manual_sync_skips_the_write_hook(self):
        """Writing a trigger field does not project either; the call does."""
        Manual = self.env["resource.scheduling.manual.test"]
        record = Manual.create(self._manual_vals())
        record._sync_reservations()

        record.date_end = datetime(2025, 1, 6, 12, 0)
        self.assertEqual(
            record.reservation_ids.date_end,
            datetime(2025, 1, 6, 17, 0),
            "the ledger still holds the pre-write window",
        )

        record._sync_reservations()
        self.assertEqual(record.reservation_ids.date_end, datetime(2025, 1, 6, 12, 0))

    def test_automatic_sync_remains_the_default(self):
        """The flag is opt-in: an ordinary consumer still projects on create."""
        record = self.Model.create(self._manual_vals())
        self.assertEqual(
            len(record.reservation_ids),
            1,
            "consumers that do not set the flag keep the CRUD hooks",
        )

    def test_manual_sync_unlink_still_cleans_the_ledger(self):
        """Only projection is deferred -- orphan cleanup is not negotiable."""
        Manual = self.env["resource.scheduling.manual.test"]
        record = Manual.create(self._manual_vals())
        record._sync_reservations()
        reservation = record.reservation_ids
        self.assertTrue(reservation.exists())

        record.unlink()
        self.assertFalse(
            reservation.exists(),
            "a deleted consumer must never leave a claim behind, however it syncs",
        )

    # ------------------------------------------------------------------
    # Conflicts on unsaved records
    # ------------------------------------------------------------------

    def _booked_day(self, percentage=100.0, name="Booked"):
        """Store one reservation covering Mon 2025-01-06, 08:00-17:00."""
        return self.Model.create(
            {
                "name": name,
                "date_start": datetime(2025, 1, 6, 8, 0),
                "date_end": datetime(2025, 1, 6, 17, 0),
                "resource_id": self.resource.id,
                "allocated_percentage": percentage,
            }
        )

    def test_unsaved_record_sees_conflict(self):
        """An unsaved record reports the clash it would create on save."""
        self._booked_day()
        self.env.invalidate_all()
        draft = self.Model.new(
            {
                "name": "Draft",
                "date_start": datetime(2025, 1, 6, 9, 0),
                "date_end": datetime(2025, 1, 6, 11, 0),
                "resource_id": self.resource.id,
                "allocated_percentage": 100.0,
            }
        )
        self.assertGreater(
            draft.schedule_overlap_count,
            0,
            "the warning must appear before the double booking is committed",
        )

    def test_unsaved_record_free_window_is_clean(self):
        """An unsaved record outside every booking reports no conflict."""
        self._booked_day()
        self.env.invalidate_all()
        draft = self.Model.new(
            {
                "name": "Draft",
                # Tuesday: the stored booking is Monday.
                "date_start": datetime(2025, 1, 7, 9, 0),
                "date_end": datetime(2025, 1, 7, 11, 0),
                "resource_id": self.resource.id,
                "allocated_percentage": 100.0,
            }
        )
        self.assertEqual(draft.schedule_overlap_count, 0)

    def test_unsaved_record_conflict_is_cumulative(self):
        """The unsaved path sweeps cumulatively, exactly like the stored one.

        Two stored 50% bookings plus an unsaved 50% is 150% on one resource,
        yet no *pair* exceeds 100%. A pairwise check -- the obvious way to
        answer this for a record with no id -- reports nothing here, and would
        have disagreed with what the same record is told the moment it is
        saved.
        """
        self._booked_day(percentage=50.0, name="Half A")
        self._booked_day(percentage=50.0, name="Half B")
        self.env.invalidate_all()
        draft = self.Model.new(
            {
                "name": "Third half",
                "date_start": datetime(2025, 1, 6, 9, 0),
                "date_end": datetime(2025, 1, 6, 11, 0),
                "resource_id": self.resource.id,
                "allocated_percentage": 50.0,
            }
        )
        self.assertGreater(draft.schedule_overlap_count, 0)

    def test_unsaved_record_without_resource_is_clean(self):
        """No resource means no claim on capacity, so nothing to conflict with."""
        self._booked_day()
        self.env.invalidate_all()
        draft = self.Model.new(
            {
                "name": "Open",
                "date_start": datetime(2025, 1, 6, 9, 0),
                "date_end": datetime(2025, 1, 6, 11, 0),
                "allocated_percentage": 100.0,
            }
        )
        self.assertEqual(draft.schedule_overlap_count, 0)

    def test_saved_record_conflicts_exclude_its_own_bookings(self):
        """``_get_schedule_conflicts`` names the peers, never the record itself."""
        first = self._booked_day(name="First")
        second = self._booked_day(name="Second")
        self.env.invalidate_all()

        conflicts = first._get_schedule_conflicts()
        self.assertTrue(conflicts, "the two full-day bookings collide")
        self.assertNotIn(
            first.reservation_ids.id,
            conflicts.ids,
            "a record must never be reported as conflicting with itself",
        )
        self.assertEqual(conflicts.ids, second.reservation_ids.ids)

    def test_unsaved_record_conflicts_match_once_saved(self):
        """The prospective answer is the one the record gets after saving."""
        self._booked_day()
        self.env.invalidate_all()
        values = {
            "name": "Draft",
            "date_start": datetime(2025, 1, 6, 9, 0),
            "date_end": datetime(2025, 1, 6, 11, 0),
            "resource_id": self.resource.id,
            "allocated_percentage": 100.0,
        }
        before = self.Model.new(values).schedule_overlap_count
        saved = self.Model.create(values)
        self.env.invalidate_all()
        self.assertEqual(before, saved.schedule_overlap_count)

    # ------------------------------------------------------------------
    # Calendar change recomputation
    # ------------------------------------------------------------------

    def test_calendar_change(self):
        """Changing the resource triggers calendar + hours recomputation."""
        record = self.Model.create(
            {
                "name": "Calendar change",
                "date_start": datetime(2025, 1, 6, 8, 0),  # Mon 8:00
                "date_end": datetime(2025, 1, 6, 17, 0),  # Mon 17:00
                "resource_id": self.resource.id,
            }
        )
        self.assertEqual(record.allocated_hours, 8.0)
        self.assertEqual(record.resource_calendar_id, self.calendar)

        # Create a resource with a half-day calendar (8:00-12:00 only)
        half_calendar = self.env["resource.calendar"].create(
            {
                "name": "Half Day Calendar",
                "tz": "UTC",
                "attendance_ids": [
                    (5, 0, 0),  # clear defaults
                    (
                        0,
                        0,
                        {
                            "name": "Mon AM",
                            "dayofweek": "0",
                            "hour_from": 8,
                            "hour_to": 12,
                            "day_period": "morning",
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "name": "Tue AM",
                            "dayofweek": "1",
                            "hour_from": 8,
                            "hour_to": 12,
                            "day_period": "morning",
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "name": "Wed AM",
                            "dayofweek": "2",
                            "hour_from": 8,
                            "hour_to": 12,
                            "day_period": "morning",
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "name": "Thu AM",
                            "dayofweek": "3",
                            "hour_from": 8,
                            "hour_to": 12,
                            "day_period": "morning",
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "name": "Fri AM",
                            "dayofweek": "4",
                            "hour_from": 8,
                            "hour_to": 12,
                            "day_period": "morning",
                        },
                    ),
                ],
            }
        )
        half_resource = self.env["resource.resource"].create(
            {
                "name": "Half Day Resource",
                "calendar_id": half_calendar.id,
                "tz": "UTC",
            }
        )
        # Reassign to a different resource → triggers calendar recompute → hours recompute
        record.resource_id = half_resource
        self.assertEqual(record.resource_calendar_id, half_calendar)
        self.assertEqual(record.allocated_hours, 4.0)


@tagged("post_install", "-at_install")
class TestSchedulingMixinAllocationBounds(TransactionCase):
    """The mixin rejects an out-of-range allocation share on the consumer.

    ``resource.reservation`` carries the same rule, but the value originates on
    the consumer: without a check here the user got a constraint violation on a
    mirror row they never see, instead of an error on the field they edited.
    A negative share is the dangerous one — the cumulative overlap sweep sums
    these numbers, so it cancels real bookings out of conflict detection.
    """

    def _record(self, **vals):
        return self.env["resource.scheduling.test"].create({"name": "bounds", **vals})

    def test_negative_allocation_rejected(self):
        with self.assertRaises(ValidationError):
            self._record(allocated_percentage=-50.0)

    def test_allocation_above_100_rejected(self):
        with self.assertRaises(ValidationError):
            self._record(allocated_percentage=150.0)

    def test_write_is_guarded_too(self):
        record = self._record(allocated_percentage=100.0)
        with self.assertRaises(ValidationError):
            record.allocated_percentage = -1.0

    def test_boundaries_accepted(self):
        self.assertTrue(self._record(allocated_percentage=0.0))
        self.assertTrue(self._record(allocated_percentage=100.0))


@tagged("post_install", "-at_install")
class TestSchedulingMixinSurplusRelease(TransactionCase):
    """Releasing a surplus reservation must not need the user's own rights.

    ``base.group_user`` holds *read-only* access to ``resource.reservation`` --
    the rows are engine-owned mirrors, written only by the projection. Creating
    one has always gone through ``sudo``; deleting a surplus one did not,
    because the recordset collecting them is built from ``self.browse()`` and
    ``union`` answers in the environment of its left operand, discarding the
    ``sudo`` the rows were fetched with. So an ordinary user who moved a
    booking from one resource to another got an AccessError from a sync that
    was only tidying up after them.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(
            cls.env, "surplus_release_user", groups="base.group_user"
        )
        cls.resource_a, cls.resource_b = cls.env["resource.resource"].create(
            [{"name": "Resource A"}, {"name": "Resource B"}]
        )

    def test_moving_a_booking_between_resources_as_a_plain_user(self):
        record = (
            self.env["resource.scheduling.test"]
            .with_user(self.user)
            .create(
                {
                    "name": "surplus",
                    "date_start": datetime(2025, 1, 6, 8, 0),
                    "date_end": datetime(2025, 1, 6, 12, 0),
                    "resource_id": self.resource_a.id,
                }
            )
        )
        # The old resource's row is now surplus and has to be released.
        record.resource_id = self.resource_b

        reservations = (
            self.env["resource.reservation"]
            .sudo()
            .with_context(active_test=False)
            .search(
                [
                    ("res_model", "=", "resource.scheduling.test"),
                    ("res_id", "=", record.id),
                ]
            )
        )
        self.assertEqual(
            reservations.resource_id,
            self.resource_b,
            "the booking moved, leaving no claim on the resource it left",
        )

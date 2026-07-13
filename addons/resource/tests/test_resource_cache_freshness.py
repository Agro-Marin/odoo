"""Regression tests for stale-read defects in resource calendar helpers.

Both cases reproduce a *stale read*: a value derived from mutable calendar
data was served from a cache (an ``@ormcache`` dict / an un-flushed SQL
column) that did not reflect a pending change made in the same transaction.
"""

from datetime import date

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestWorkingHoursFreshness(TransactionCase):
    """``_works_on_date`` / ``_get_working_hours`` must reflect attendance edits.

    Regression: ``_get_working_hours`` was ``@ormcache('self.id')`` but nothing
    in the module ever invalidates ormcaches, so once a calendar's working days
    were cached, adding or removing an attendance line left the cached answer
    stale for the lifetime of the worker (affecting leave/planning consumers
    such as ``l10n_fr_hr_holidays`` and ``website_sale_renting_planning``).
    """

    SATURDAY = date(2025, 1, 11)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.calendar = cls.env["resource.calendar"].create(
            {"name": "Freshness", "tz": "UTC"}
        )

    def test_works_on_date_reflects_added_attendance(self):
        # Prime the (formerly cached) working-days map: standard calendar has
        # no Saturday attendance.
        self.assertFalse(self.calendar._works_on_date(self.SATURDAY))

        self.env["resource.calendar.attendance"].create(
            {
                "name": "Saturday shift",
                "calendar_id": self.calendar.id,
                "dayofweek": "5",
                "hour_from": 8,
                "hour_to": 12,
                "day_period": "morning",
            }
        )
        # Must observe the new working day, not a stale cached "no Saturday".
        self.assertTrue(
            self.calendar._works_on_date(self.SATURDAY),
            "adding a Saturday attendance must make _works_on_date True",
        )

    def test_works_on_date_reflects_removed_attendance(self):
        monday = date(2025, 1, 6)
        self.assertTrue(self.calendar._works_on_date(monday))

        self.calendar.attendance_ids.filtered(lambda a: a.dayofweek == "0").unlink()
        self.assertFalse(
            self.calendar._works_on_date(monday),
            "removing every Monday attendance must make _works_on_date False",
        )

    def test_get_working_hours_returns_independent_mapping(self):
        """The map must not be a shared mutable object across calls.

        (The old ormcached ``defaultdict`` was mutated in place by lookups of
        missing keys.)"""
        first = self.calendar._get_working_hours()
        # A missing-key lookup on a defaultdict inserts a default; it must not
        # leak into the next call's result.
        _ = first["0"]["6"]
        second = self.calendar._get_working_hours()
        self.assertNotIn("6", second.get("0", {}))


@tagged("post_install", "-at_install")
class TestSearchWorkTimeRateFreshness(TransactionCase):
    """``_search_work_time_rate`` must see pending (un-flushed) rate changes.

    Regression: the search ran raw SQL on the stored ``hours_per_week`` /
    ``full_time_required_hours`` columns during domain optimisation — before
    the ORM flushes them for the outer query — so a calendar whose rate had
    changed in cache but not yet in the table was mis-filtered.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Calendar = cls.env["resource.calendar"]
        # A part-time calendar (Mon-Fri mornings only ⇒ 20h/week ⇒ 50% rate).
        cls.calendar = cls.Calendar.create({"name": "Part time", "tz": "UTC"})
        cls.calendar.attendance_ids.unlink()
        cls.env["resource.calendar.attendance"].create(
            [
                {
                    "name": f"AM {d}",
                    "calendar_id": cls.calendar.id,
                    "dayofweek": str(d),
                    "hour_from": 8,
                    "hour_to": 12,
                    "day_period": "morning",
                }
                for d in range(5)
            ]
        )

    def test_search_reflects_pending_rate_change(self):
        # Make sure the part-time rate (~50%) is on disk.
        self.env.flush_all()
        self.assertLess(self.calendar.work_time_rate, 60)

        # Promote to full time (add afternoons) but DO NOT flush: the
        # recompute of hours_per_week is now pending in cache only.
        self.env["resource.calendar.attendance"].create(
            [
                {
                    "name": f"PM {d}",
                    "calendar_id": self.calendar.id,
                    "dayofweek": str(d),
                    "hour_from": 13,
                    "hour_to": 17,
                    "day_period": "afternoon",
                }
                for d in range(5)
            ]
        )
        # The search must honour the pending full-time rate, not the stale 50%.
        results = self.Calendar.search([("work_time_rate", ">", 80)])
        self.assertIn(
            self.calendar,
            results,
            "search must see the pending full-time rate, not the stale DB value",
        )

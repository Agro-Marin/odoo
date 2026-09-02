from datetime import date

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestWorkingHoursFreshness(TransactionCase):
    SATURDAY = date(2025, 1, 11)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.calendar = cls.env["resource.calendar"].create(
            {"name": "Freshness", "tz": "UTC"}
        )

    def test_works_on_date_reflects_added_attendance(self):
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
        first = self.calendar._get_working_hours()
        _ = first["0"]["6"]
        second = self.calendar._get_working_hours()
        self.assertNotIn("6", second.get("0", {}))


@tagged("post_install", "-at_install")
class TestSearchWorkTimeRateFreshness(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Calendar = cls.env["resource.calendar"]
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
        self.env.flush_all()
        self.assertLess(self.calendar.work_time_rate, 60)

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
        results = self.Calendar.search([("work_time_rate", ">", 80)])
        self.assertIn(
            self.calendar,
            results,
            "search must see the pending full-time rate, not the stale DB value",
        )

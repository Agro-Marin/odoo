"""Regression tests for two timezone-handling defects in the resource module.

1. ``resource.calendar.leaves._compute_date_to`` resolved its fallback timezone
   once from ``self.company_id`` — a multi-record recordset — which raised
   ``ValueError: Expected singleton`` whenever a batch of leaves spanned several
   companies *and* the acting user had no ``tz`` (so the code reached the
   ``self.company_id.resource_calendar_id.tz`` fallback).  In the ``create``
   path this surfaced as a failed insert / ``NotNullViolation`` on ``date_to``.
   It was also semantically wrong: every leave in a mixed-company batch would
   have been end-dated in a single, arbitrary company's timezone.

2. ``resource.calendar._work_intervals_batch`` / ``_attendance_intervals_batch``
   / ``_leave_intervals_batch`` advertise ``tz: BaseTzInfo | str | None`` yet
   fed the value straight to ``.astimezone(tz)`` / dict keys, so a *string*
   timezone name raised ``TypeError: tzinfo argument must be ...``.
"""

from datetime import datetime

import pytz

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

UTC = pytz.UTC


@tagged("post_install", "-at_install")
class TestLeaveDateToMultiCompanyTz(TransactionCase):
    """``_compute_date_to`` must resolve the timezone per leave, not once from
    the (possibly multi-company) recordset."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.env["res.company"].create({"name": "TZ Co A"})
        cls.company_b = cls.env["res.company"].create({"name": "TZ Co B"})
        # Distinct calendar timezones so a per-leave resolution is observable.
        cls.company_a.resource_calendar_id.tz = "Europe/Brussels"  # UTC+1 in Jan
        cls.company_b.resource_calendar_id.tz = "Asia/Tokyo"  # UTC+9

    def _tzless_leaves_model(self):
        """A leaves model bound to a tz-less superuser and no context tz, with
        both test companies allowed — this forces the fallback branch."""
        root = self.env.ref("base.user_root")
        root.tz = False
        return (
            self.env["resource.calendar.leaves"]
            .sudo()
            .with_context(
                tz=None,
                allowed_company_ids=[self.company_a.id, self.company_b.id],
            )
        )

    def test_multi_company_batch_create_does_not_raise(self):
        """Creating leaves across companies in one call must succeed."""
        leaves = self._tzless_leaves_model().create(
            [
                {
                    "name": "A",
                    "calendar_id": self.company_a.resource_calendar_id.id,
                    "date_from": datetime(2025, 1, 6, 8, 0),
                },
                {
                    "name": "B",
                    "calendar_id": self.company_b.resource_calendar_id.id,
                    "date_from": datetime(2025, 1, 6, 8, 0),
                },
            ]
        )
        # Both records were inserted with a non-null date_to.
        self.assertEqual(len(leaves), 2)
        self.assertTrue(all(leaves.mapped("date_to")))

    def test_date_to_uses_each_leaves_own_calendar_tz(self):
        """Each leave is end-dated at 23:59:59 of its own calendar's timezone."""
        leaves = self._tzless_leaves_model().create(
            [
                {
                    "name": "A",
                    "calendar_id": self.company_a.resource_calendar_id.id,
                    "date_from": datetime(2025, 1, 6, 8, 0),
                },
                {
                    "name": "B",
                    "calendar_id": self.company_b.resource_calendar_id.id,
                    "date_from": datetime(2025, 1, 6, 8, 0),
                },
            ]
        )
        leave_a, leave_b = leaves[0], leaves[1]
        # Brussels: 2025-01-06 23:59:59 CET == 2025-01-06 22:59:59 UTC
        self.assertEqual(leave_a.date_to, datetime(2025, 1, 6, 22, 59, 59))
        # Tokyo:    2025-01-06 23:59:59 JST == 2025-01-06 14:59:59 UTC
        self.assertEqual(leave_b.date_to, datetime(2025, 1, 6, 14, 59, 59))


@tagged("post_install", "-at_install")
class TestIntervalBatchStringTz(TransactionCase):
    """The interval helpers must accept a string tz name, matching their type
    hints, and produce the same result as the equivalent ``tzinfo``."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.calendar = cls.env["resource.calendar"].create(
            {"name": "String TZ", "tz": "UTC"}
        )
        cls.resource = cls.env["resource.resource"].create(
            {"name": "STZ res", "calendar_id": cls.calendar.id, "tz": "UTC"}
        )
        cls.env["resource.calendar.leaves"].create(
            {
                "name": "Global off",
                "calendar_id": cls.calendar.id,
                "date_from": datetime(2025, 1, 8, 0, 0),
                "date_to": datetime(2025, 1, 8, 23, 59),
            }
        )
        cls.start = UTC.localize(datetime(2025, 1, 6, 0, 0))
        cls.end = UTC.localize(datetime(2025, 1, 11, 0, 0))
        cls.tz_str = "Europe/Brussels"
        cls.tz_obj = pytz.timezone("Europe/Brussels")

    def test_attendance_intervals_string_tz(self):
        by_str = self.calendar._attendance_intervals_batch(
            self.start, self.end, self.resource, tz=self.tz_str
        )
        by_obj = self.calendar._attendance_intervals_batch(
            self.start, self.end, self.resource, tz=self.tz_obj
        )
        self.assertEqual(list(by_str[self.resource.id]), list(by_obj[self.resource.id]))

    def test_leave_intervals_string_tz(self):
        by_str = self.calendar._leave_intervals_batch(
            self.start, self.end, self.resource, tz=self.tz_str
        )
        by_obj = self.calendar._leave_intervals_batch(
            self.start, self.end, self.resource, tz=self.tz_obj
        )
        self.assertEqual(list(by_str[self.resource.id]), list(by_obj[self.resource.id]))

    def test_work_intervals_string_tz(self):
        by_str = self.calendar._work_intervals_batch(
            self.start, self.end, self.resource, tz=self.tz_str
        )
        by_obj = self.calendar._work_intervals_batch(
            self.start, self.end, self.resource, tz=self.tz_obj
        )
        self.assertEqual(list(by_str[self.resource.id]), list(by_obj[self.resource.id]))

    def test_unavailable_intervals_string_tz(self):
        """The public forwarder also accepts a string tz without raising."""
        by_str = self.calendar._unavailable_intervals_batch(
            self.start, self.end, self.resource, tz=self.tz_str
        )
        by_obj = self.calendar._unavailable_intervals_batch(
            self.start, self.end, self.resource, tz=self.tz_obj
        )
        self.assertEqual(by_str[self.resource.id], by_obj[self.resource.id])

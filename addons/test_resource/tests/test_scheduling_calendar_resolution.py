from datetime import datetime

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestSchedulingCalendarResolution(TransactionCase):
    """Which working calendar governs a record being scheduled.

    ``_scheduling_resolve_calendar`` walks a four-step fallback: an explicit
    resource, the record's own calendar, its company's, then the current
    company's. Everything scheduled on the record -- when work may start,
    which hours count -- follows from the answer.
    """

    MODEL_NAME = "resource.scheduling.test"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Calendar = cls.env["resource.calendar"]
        cls.resource_calendar = Calendar.create({"name": "Resource hours", "tz": "UTC"})
        cls.record_calendar = Calendar.create({"name": "Record hours", "tz": "UTC"})
        cls.company_calendar = cls.env.company.resource_calendar_id

        cls.resource_with_hours = cls.env["resource.resource"].create(
            {"name": "Staffed", "calendar_id": cls.resource_calendar.id}
        )
        cls.resource_without_hours = cls.env["resource.resource"].create(
            {"name": "Unstaffed", "calendar_id": cls.resource_calendar.id}
        )
        cls.resource_without_hours.calendar_id = False

    def _record(self, calendar=None):
        record = self.env[self.MODEL_NAME].create({"name": "Scheduled work"})
        record.resource_calendar_id = calendar or False
        return record

    def test_an_explicit_resource_decides_the_hours(self):
        """A resource passed in outranks the record's own calendar."""
        record = self._record(self.record_calendar)
        self.assertEqual(
            record._scheduling_resolve_calendar(resource=self.resource_with_hours),
            self.resource_calendar,
        )

    def test_a_resource_without_hours_does_not_decide_anything(self):
        """An empty resource falls through instead of erasing the calendar.

        Taking it as the answer would leave the record with no working hours
        at all (negative).
        """
        record = self._record(self.record_calendar)
        self.assertEqual(
            record._scheduling_resolve_calendar(resource=self.resource_without_hours),
            self.record_calendar,
        )

    def test_the_record_keeps_its_own_hours_when_no_resource_is_given(self):
        """Asked on its own, the record answers with its calendar."""
        record = self._record(self.record_calendar)
        self.assertEqual(record._scheduling_resolve_calendar(), self.record_calendar)

    def test_a_record_without_hours_falls_back_to_its_company(self):
        """Nothing set on the record means the company's working hours."""
        record = self._record()
        self.assertFalse(record.resource_calendar_id)
        self.assertEqual(record._scheduling_resolve_calendar(), self.company_calendar)

    def test_the_fallback_never_answers_with_nothing(self):
        """The chain always ends on a calendar, never on an empty one.

        A record with no hours anywhere would silently schedule nothing.
        """
        record = self._record()
        self.assertTrue(record._scheduling_resolve_calendar())

    def test_snapping_a_span_with_no_working_hours_leaves_it_alone(self):
        """A weekend holds no work intervals, so nothing is snapped to.

        Collapsing it onto an unrelated interval would silently move the
        work to another day (negative). 2025-01-11 and 12 are Sat and Sun.
        """
        record = self._record(self.record_calendar)
        start = datetime(2025, 1, 11, 9, 0)
        end = datetime(2025, 1, 12, 17, 0)
        self.assertEqual(record._scheduling_snap_to_calendar(start, end), (start, end))

    def test_snapping_without_dates_returns_them_unchanged(self):
        """Missing dates are handed back rather than invented (negative)."""
        record = self._record(self.record_calendar)
        self.assertEqual(
            record._scheduling_snap_to_calendar(False, False),
            (False, False),
        )

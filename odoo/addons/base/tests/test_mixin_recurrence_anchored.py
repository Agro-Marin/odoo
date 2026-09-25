from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestRecurrenceAnchors(TransactionCase):
    def _anchored(self, **vals):
        return self.env["mixin.recurrence.anchored"].new(vals)

    def test_a_missing_day_or_month_is_refused(self):
        for vals in (
            {"repeat_unit": "month", "repeat_day": False},
            {"repeat_unit": "year", "repeat_day": False},
            {"repeat_unit": "year", "repeat_month": False},
            {
                "repeat_unit": "year",
                "repeat_twice": True,
                "repeat_second_day": "1",
                "repeat_second_month": False,
            },
        ):
            with self.subTest(vals=vals), self.assertRaises(ValidationError):
                self._anchored(**vals)._check_repeat_anchors()

    def test_twice_monthly_days_that_meet_in_a_short_month_are_refused(self):
        for first, second in (("30", "31"), ("28", "last"), ("31", "last")):
            anchored = self._anchored(
                repeat_unit="month",
                repeat_twice=True,
                repeat_day=first,
                repeat_second_day=second,
            )
            with self.subTest(days=(first, second)), self.assertRaises(ValidationError):
                anchored._check_repeat_anchors()

    def test_twice_yearly_dates_that_meet_outside_a_leap_year_are_refused(self):
        anchored = self._anchored(
            repeat_unit="year",
            repeat_twice=True,
            repeat_day="29",
            repeat_month="2",
            repeat_second_day="last",
            repeat_second_month="2",
        )
        with self.assertRaises(ValidationError):
            anchored._check_repeat_anchors()

    def test_distinct_days_are_accepted(self):
        for first, second in (("27", "28"), ("15", "last"), ("1", "15")):
            with self.subTest(days=(first, second)):
                self._anchored(
                    repeat_unit="month",
                    repeat_twice=True,
                    repeat_day=first,
                    repeat_second_day=second,
                )._check_repeat_anchors()

from datetime import datetime

from dateutil.relativedelta import relativedelta

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestMaintenanceRecurrenceRule(TransactionCase):
    def test_the_request_takes_its_recurrence_vocabulary_from_the_mixin(self):
        request = self.env["maintenance.request"]
        self.assertIn(
            "mixin.recurrence.rule",
            {getattr(base, "_name", None) for base in type(request).__mro__},
        )
        self.assertEqual(
            request._fields["repeat_unit"].selection,
            self.env["mixin.recurrence.rule"]._fields["repeat_unit"].selection,
        )

    def test_the_step_matches_the_hand_rolled_relativedelta_it_replaced(self):
        # maintenance built its own step as relativedelta(**{f"{unit}s": qty}).
        # A base of Jan-31 is what makes month and year rollover disagree if the
        # two ever stop meaning the same thing.
        request = self.env["maintenance.request"]
        base = datetime(2026, 1, 31, 12, 0, 0)
        for unit in ("day", "week", "month", "year"):
            for qty in (1, 2, 3, 7, 12, 13, 52, 365):
                record = request.new({"repeat_unit": unit, "repeat_interval": qty})
                self.assertEqual(
                    base + record._get_recurrence_delta(),
                    base + relativedelta(**{f"{unit}s": qty}),
                    f"step diverged for {qty} {unit}",
                )

    def test_a_non_positive_interval_is_still_rejected(self):
        for interval in (-5, -1, 0):
            with self.assertRaises(ValidationError):
                self.env["maintenance.request"].create(
                    {
                        "name": "probe",
                        "repeat_interval": interval,
                    }
                )

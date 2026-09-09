from datetime import date

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestAccrualDateWindow(TransactionCase):
    def _window(self, **context):
        return {
            leaf[1]: leaf[2]
            for leaf in self.env["mixin.analytic"]
            .with_context(**context)
            ._get_accrual_date_window("order_id.date_order")
        }

    def test_the_bound_is_exclusive_on_the_following_day(self):
        window = self._window()
        self.assertNotIn(
            "<=", window, "an inclusive bound excludes the day's own orders"
        )
        today = fields.Date.today()
        self.assertEqual(window["<"], today + relativedelta(days=1))
        self.assertEqual(window[">="], today - relativedelta(years=1))

    def test_the_window_follows_the_requested_accrual_date(self):
        window = self._window(accrual_entry_date="2020-06-15")
        self.assertEqual(window[">="], date(2019, 6, 15))
        self.assertEqual(window["<"], date(2020, 6, 16))

    def test_a_leap_day_inside_the_window_does_not_shift_its_ends(self):
        window = self._window(accrual_entry_date="2024-03-01")
        self.assertEqual(window[">="], date(2023, 3, 1))
        self.assertEqual(window["<"], date(2024, 3, 2))
        self.assertEqual(
            (window["<"] - window[">="]).days,
            367,
            "which is why the first test asserts offsets rather than this number",
        )

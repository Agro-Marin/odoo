from datetime import date

from dateutil.relativedelta import relativedelta

from odoo.tests import TransactionCase, tagged


@tagged("mail_activity")
class TestMixinDelay(TransactionCase):
    CONSUMERS = ("mail.activity.type", "mail.activity.plan.template")

    def test_both_consumers_take_the_vocabulary_from_the_mixin(self):
        mixin_selection = self.env["mixin.delay"]._fields["delay_unit"].selection
        for model in self.CONSUMERS:
            with self.subTest(model=model):
                self.assertIn(
                    "mixin.delay",
                    {
                        getattr(base, "_name", None)
                        for base in type(self.env[model]).__mro__
                    },
                )
                self.assertEqual(
                    self.env[model]._fields["delay_unit"].selection, mixin_selection
                )

    def test_the_step_matches_the_hand_rolled_relativedelta_it_replaced(self):
        # Both consumers spelled the step as relativedelta(**{unit: count}), and
        # hr_holidays a third time. A Jan-31 base is what makes a month step
        # disagree if the two ever stop meaning the same thing.
        base = date(2026, 1, 31)
        for unit in ("days", "weeks", "months"):
            for count in (0, 1, 2, 3, 7, 12, 13, 52):
                record = self.env["mail.activity.type"].new(
                    {"delay_unit": unit, "delay_count": count}
                )
                self.assertEqual(
                    base + record._get_delay_delta(),
                    base + relativedelta(**{unit: count}),
                    f"step diverged for {count} {unit}",
                )

    def test_every_stored_unit_survives_the_singular_mapping(self):
        # _get_delay_delta drops a trailing "s" to reach get_timedelta, whose
        # granularity is singular. A stored value that mapping cannot handle
        # would raise rather than answer.
        for unit, _label in self.env["mixin.delay"]._fields["delay_unit"].selection:
            with self.subTest(unit=unit):
                record = self.env["mail.activity.type"].new(
                    {"delay_unit": unit, "delay_count": 1}
                )
                self.assertEqual(
                    date(2026, 1, 1) + record._get_delay_delta(),
                    date(2026, 1, 1) + relativedelta(**{unit: 1}),
                )

    def test_delay_from_stayed_with_each_consumer(self):
        # The mixin deliberately does not own delay_from: the two consumers ask
        # different questions with it, and a field carries one selection.
        activity_type = dict(
            self.env["mail.activity.type"]._fields["delay_from"].selection
        )
        template = dict(
            self.env["mail.activity.plan.template"]._fields["delay_from"].selection
        )
        self.assertNotEqual(activity_type, template)
        self.assertNotIn("delay_from", self.env["mixin.delay"]._fields)

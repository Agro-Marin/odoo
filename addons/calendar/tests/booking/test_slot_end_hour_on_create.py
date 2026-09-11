from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSlotEndHourOnCreate(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.appointment_type = cls.env["appointment.type"].create(
            {"name": "Evening consult", "appointment_duration": 1.0}
        )

    def _slot(self, **vals):
        return self.env["appointment.slot"].create(
            {"appointment_type_id": self.appointment_type.id, "weekday": "1", **vals}
        )

    def test_a_slot_starting_after_the_default_end_ends_one_duration_later(self):
        self.assertEqual(self._slot(start_hour=18.0).end_hour, 19.0)

    def test_a_morning_slot_keeps_the_default_end(self):
        self.assertEqual(self._slot(start_hour=9.0).end_hour, 17.0)

    def test_an_explicit_end_hour_is_kept(self):
        self.assertEqual(self._slot(start_hour=18.0, end_hour=0.0).end_hour, 0.0)

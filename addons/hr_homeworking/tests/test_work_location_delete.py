# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.exceptions import UserError
from odoo.fields import Date
from odoo.tests import TransactionCase, tagged

from odoo.addons.hr_homeworking.models.hr_homeworking import DAYS

# subir-cobertura for the remote-work day-location helper and the work-location
# delete guard.


@tagged("post_install", "-at_install")
class TestHrHomeworkingWorkLocation(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.address = cls.env["res.partner"].create({"name": "HQ"})
        cls.location = cls.env["hr.work.location"].create(
            {"name": "Office", "location_type": "office", "address_id": cls.address.id}
        )

    def test_current_day_field_matches_today(self):
        """The current-day location field matches today's weekday."""
        field = self.env["hr.employee"]._get_current_day_location_field()
        self.assertIn(field, DAYS)
        self.assertEqual(field, DAYS[Date.today().weekday()])

    def test_unused_location_can_be_deleted(self):
        """A work location no employee uses can be deleted."""
        spare = self.env["hr.work.location"].create(
            {"name": "Spare", "location_type": "other", "address_id": self.address.id}
        )
        spare.unlink()
        self.assertFalse(spare.exists())

    def test_location_used_every_day_cannot_be_deleted(self):
        """A work location assigned to an employee's week cannot be deleted."""
        self.env["hr.employee"].create(
            {"name": "Remote worker", **dict.fromkeys(DAYS, self.location.id)}
        )
        with self.assertRaises(UserError):
            self.location.unlink()

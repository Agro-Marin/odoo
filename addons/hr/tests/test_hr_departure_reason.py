from odoo.tests import TransactionCase


class TestHrDepartureReasonArchive(TransactionCase):
    """A departure reason that fell out of use has to leave the pickers.

    Deleting one is not an option: the three shipped reasons are refused by
    ``_unlink_except_default_departure_reasons`` and any reason already written
    on a version is held by the foreign key.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.reason = cls.env["hr.departure.reason"].create(
            {"name": "Programa temporal 2019", "sequence": 99}
        )

    def test_unused_reason_can_be_archived(self):
        self.reason.action_archive()

        self.assertFalse(self.reason.active)
        self.assertNotIn(self.reason, self.env["hr.departure.reason"].search([]))
        self.assertIn(
            self.reason,
            self.env["hr.departure.reason"].with_context(active_test=False).search([]),
        )

    def test_archived_reason_is_not_offered_in_the_picker(self):
        self.assertTrue(self.env["hr.departure.reason"].name_search("Programa"))

        self.reason.action_archive()

        self.assertFalse(self.env["hr.departure.reason"].name_search("Programa"))

    def test_archived_reason_stays_on_the_departures_that_used_it(self):
        employee = self.env["hr.employee"].create({"name": "Rita"})
        employee.departure_reason_id = self.reason

        self.reason.action_archive()

        self.assertEqual(employee.departure_reason_id, self.reason)
        self.assertEqual(employee.departure_reason_id.name, "Programa temporal 2019")

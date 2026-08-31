from odoo.tests import TransactionCase


class TestPayrollStructureTypeWorkingHours(TransactionCase):
    """The Working Hours picker must not offer another company's schedule.

    ``marin_data`` ships one ``Standard 45 hours/week`` calendar per company, so
    an unfiltered picker shows several entries carrying the very same label and
    nothing to tell them apart.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_north, cls.company_south = cls.env["res.company"].create(
            [{"name": "Marin Norte"}, {"name": "Marin Sur"}]
        )
        cls.calendar_north, cls.calendar_south = cls.env["resource.calendar"].create(
            [
                {
                    "name": "Standard 45 hours/week",
                    "company_id": cls.company_north.id,
                },
                {
                    "name": "Standard 45 hours/week",
                    "company_id": cls.company_south.id,
                },
            ]
        )
        cls.calendar_shared = cls.env["resource.calendar"].create(
            {"name": "Standard 45 hours/week", "company_id": False}
        )

    def _offered_calendars(self):
        """What the client would list under Working Hours for Marin Norte."""
        structure_type = self.env["hr.payroll.structure.type"].with_context(
            allowed_company_ids=self.company_north.ids
        )
        description = structure_type.fields_get(["default_resource_calendar_id"])
        domain = description["default_resource_calendar_id"]["domain"] or []
        return self.env["resource.calendar"].search(domain)

    def test_picker_keeps_the_active_company_schedule(self):
        self.assertIn(self.calendar_north, self._offered_calendars())

    def test_picker_keeps_a_schedule_that_belongs_to_no_company(self):
        self.assertIn(self.calendar_shared, self._offered_calendars())

    def test_picker_drops_another_company_schedule(self):
        self.assertNotIn(self.calendar_south, self._offered_calendars())

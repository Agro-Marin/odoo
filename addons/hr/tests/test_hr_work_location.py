from odoo.tests import Form, TransactionCase


class TestHrWorkLocationAddress(TransactionCase):
    """A location the employee works from home has no work address to give."""

    def test_home_location_saves_without_a_work_address(self):
        location_form = Form(self.env["hr.work.location"])
        location_form.name = "Casa"
        location_form.location_type = "home"

        location = location_form.save()

        self.assertFalse(location.address_id)

    def test_office_location_still_demands_a_work_address(self):
        location_form = Form(self.env["hr.work.location"])
        location_form.name = "Planta Culiacan"
        location_form.location_type = "office"

        with self.assertRaises(AssertionError):
            location_form.save()

    def test_location_type_is_labelled_for_what_it_picks(self):
        description = self.env["hr.work.location"].fields_get(["location_type"])

        self.assertEqual(description["location_type"]["string"], "Icon")

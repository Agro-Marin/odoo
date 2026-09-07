from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCreateReachesTheParty(TransactionCase):
    """A value given to hr.employee.create is held by the party, not beside it."""

    GIVEN = {
        "name": "Created Person",
        "work_email": "created@work.test",
        "tz": "Europe/Brussels",
    }
    ON_THE_PARTY = {"name": "name", "work_email": "email", "tz": "tz", "lang": "lang"}

    def test_every_identity_value_given_at_create_reaches_the_party(self):
        employee = self.env["hr.employee"].create(dict(self.GIVEN))
        for fname, given in self.GIVEN.items():
            with self.subTest(field=fname):
                self.assertEqual(employee.partner_id[self.ON_THE_PARTY[fname]], given)

    def test_the_employee_and_its_party_never_disagree(self):
        employee = self.env["hr.employee"].create(dict(self.GIVEN))
        for fname, party_fname in self.ON_THE_PARTY.items():
            with self.subTest(field=fname):
                self.assertEqual(employee[fname], employee.partner_id[party_fname])

    def test_the_resource_carries_the_timezone_given_at_create(self):
        employee = self.env["hr.employee"].create(
            {"name": "Zoned Two", "tz": "Europe/Brussels"}
        )
        self.assertEqual(employee.resource_id.tz, "Europe/Brussels")

    def test_a_language_given_at_create_reaches_the_party(self):
        employee = self.env["hr.employee"].create(
            {"name": "Spoken", "lang": self.env.user.lang}
        )
        self.assertEqual(employee.partner_id.lang, self.env.user.lang)

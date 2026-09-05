from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, tagged

from odoo.addons.mail.tests.common import mail_new_test_user


@tagged("post_install", "-at_install")
class TestPartyIdentifiers(TransactionCase):
    """The employee's identifiers are rows of res.partner.identifier on its party."""

    def _rows(self, employee):
        return {i.type_id.code: i for i in employee.partner_id.identifier_ids}

    def test_create_lands_on_the_party(self):
        employee = self.env["hr.employee"].create(
            {
                "name": "Ident",
                "identification_id": "NIN-1",
                "ssnid": "123-45-6789",
                "passport_id": "P0001",
                "passport_expiration_date": "2030-01-31",
                "barcode": "041000000001",
            }
        )
        rows = self._rows(employee)
        self.assertEqual(rows["NATIONAL_ID"].value, "NIN-1")
        self.assertEqual(rows["SSN"].value, "123-45-6789")
        self.assertEqual(rows["PASSPORT"].value, "P0001")
        self.assertEqual(str(rows["PASSPORT"].valid_until), "2030-01-31")
        self.assertEqual(rows["BADGE"].value, "041000000001")
        self.assertEqual(employee.ssnid, "123-45-6789")
        self.assertEqual(str(employee.passport_expiration_date), "2030-01-31")

    def test_clearing_a_value_removes_its_row(self):
        employee = self.env["hr.employee"].create({"name": "Ident Clear", "ssnid": "1"})
        self.assertIn("SSN", self._rows(employee))
        employee.ssnid = False
        self.assertNotIn("SSN", self._rows(employee))

    def test_a_badge_is_searchable_and_unique(self):
        first = self.env["hr.employee"].create({"name": "Badge A", "barcode": "BADGE1"})
        found = self.env["hr.employee"].search([("barcode", "=", "BADGE1")])
        self.assertEqual(found, first)
        self.assertIn(first, self.env["hr.employee"].search([("barcode", "!=", False)]))
        self.assertNotIn(
            first, self.env["hr.employee"].search([("barcode", "=", False)])
        )
        with self.assertRaises(ValidationError):
            self.env["hr.employee"].create({"name": "Badge B", "barcode": "badge1"})

    def test_a_badge_is_alphanumeric_and_short(self):
        with self.assertRaises(ValidationError):
            self.env["hr.employee"].create(
                {"name": "Badge Bad", "barcode": "no spaces!"}
            )

    def test_generating_badges_still_works(self):
        employees = self.env["hr.employee"].create(
            [{"name": "Gen A"}, {"name": "Gen B"}]
        )
        employees.action_generate_random_barcode()
        self.assertEqual(len(set(employees.mapped("barcode"))), 2)
        self.assertTrue(all(b.startswith("041") for b in employees.mapped("barcode")))

    def test_a_colleague_cannot_read_them_through_the_employee(self):
        employee = self.env["hr.employee"].create(
            {"name": "Ident Hidden", "ssnid": "9"}
        )
        colleague = mail_new_test_user(
            self.env, login="ident_colleague", groups="base.group_user"
        )
        with self.assertRaises(AccessError):
            employee.with_user(colleague).read(["ssnid"])
        self.assertFalse(
            self.env["res.partner.identifier"]
            .with_user(colleague)
            .search([("partner_id", "=", employee.partner_id.id)])
        )

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
                "ssnid": "123456789",
                "passport_id": "P0001",
                "passport_expiration_date": "2030-01-31",
                "barcode": "041000000001",
            }
        )
        rows = self._rows(employee)
        self.assertEqual(rows["NATIONAL_ID"].value, "NIN-1")
        self.assertEqual(rows["SSN"].value, "123456789")
        self.assertEqual(rows["PASSPORT"].value, "P0001")
        self.assertEqual(str(rows["PASSPORT"].valid_until), "2030-01-31")
        self.assertEqual(rows["BADGE"].value, "041000000001")
        self.assertEqual(employee.ssnid, "123456789")
        self.assertEqual(str(employee.passport_expiration_date), "2030-01-31")

    def test_linking_a_user_moves_the_identifiers(self):
        employee = self.env["hr.employee"].create(
            {"name": "Badged", "barcode": "041000000002", "identification_id": "NIN-2"}
        )
        former = employee.partner_id
        user = mail_new_test_user(self.env, login="badged", name="Badged")
        employee.user_id = user
        self.assertNotEqual(employee.partner_id, former)
        self.assertEqual(employee.barcode, "041000000002")
        self.assertEqual(employee.identification_id, "NIN-2")
        self.assertEqual(
            self.env["hr.employee"].search([("barcode", "=", "041000000002")]), employee
        )
        self.assertFalse(former.identifier_ids)

    def test_a_timezone_given_at_create_reaches_the_party(self):
        employee = self.env["hr.employee"].create(
            {"name": "Zoned", "tz": "Europe/Brussels"}
        )
        self.assertEqual(employee.partner_id.tz, "Europe/Brussels")
        self.assertEqual(employee.resource_id.tz, "Europe/Brussels")

    def test_clearing_a_value_removes_its_row(self):
        employee = self.env["hr.employee"].create(
            {"name": "Ident Clear", "ssnid": "111111111"}
        )
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
            {"name": "Ident Hidden", "ssnid": "999999999"}
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

    def test_the_passport_expiry_can_be_searched(self):
        Employee = self.env["hr.employee"]
        expiring = Employee.create(
            {
                "name": "Passport Expiring",
                "passport_id": "P-SOON",
                "passport_expiration_date": "2030-02-10",
            }
        )
        later = Employee.create(
            {
                "name": "Passport Later",
                "passport_id": "P-LATER",
                "passport_expiration_date": "2031-02-10",
            }
        )
        none = Employee.create({"name": "No Passport"})
        undated_holder = Employee.create(
            {"name": "Passport Undated", "passport_id": "P-UNDATED"}
        )
        window = Employee.search(
            [
                ("passport_expiration_date", ">=", "2030-01-01"),
                ("passport_expiration_date", "<=", "2030-12-31"),
            ]
        )
        self.assertIn(expiring, window)
        self.assertNotIn(later, window)
        self.assertNotIn(none, window)
        self.assertNotIn(undated_holder, window)
        undated = Employee.search([("passport_expiration_date", "=", False)])
        self.assertIn(none, undated)
        self.assertIn(undated_holder, undated)
        self.assertNotIn(expiring, undated)
        dated = Employee.search([("passport_expiration_date", "!=", False)])
        self.assertIn(expiring, dated)
        self.assertNotIn(none, dated)
        self.assertNotIn(undated_holder, dated)

    def test_an_absent_identifier_can_be_searched(self):
        Employee = self.env["hr.employee"]
        carrying = Employee.create({"name": "Has Passport", "passport_id": "P-HAS"})
        lacking = Employee.create({"name": "Lacks Passport"})
        without = Employee.search([("passport_id", "=", False)])
        self.assertIn(lacking, without)
        self.assertNotIn(carrying, without)
        with_one = Employee.search([("passport_id", "!=", False)])
        self.assertIn(carrying, with_one)
        self.assertNotIn(lacking, with_one)

    def test_an_expiry_cannot_be_recorded_without_its_document(self):
        Employee = self.env["hr.employee"]
        for expiry in (
            "visa_expire",
            "work_permit_expiration_date",
            "passport_expiration_date",
        ):
            with self.subTest(expiry=expiry), self.assertRaises(ValidationError):
                Employee.create({"name": "Dateless", expiry: "2030-01-01"})

    def test_clearing_the_document_number_refuses_to_orphan_its_expiry(self):
        employee = self.env["hr.employee"].create(
            {
                "name": "Passport Holder",
                "passport_id": "P-CLEAR",
                "passport_expiration_date": "2030-01-01",
            }
        )
        with self.assertRaises(ValidationError):
            employee.passport_id = False
        employee.write({"passport_id": False, "passport_expiration_date": False})
        self.assertFalse(self._rows(employee).get("PASSPORT"))

    def test_the_document_and_its_expiry_are_accepted_together(self):
        employee = self.env["hr.employee"].create(
            {
                "name": "Permit Holder",
                "permit_no": "WP-1",
                "work_permit_expiration_date": "2030-01-01",
                "visa_no": "V-1",
                "visa_expire": "2031-01-01",
            }
        )
        self.assertEqual(employee.permit_no, "WP-1")
        self.assertEqual(employee.visa_no, "V-1")

from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged

from odoo.addons.mail.tests.common import mail_new_test_user


@tagged("post_install", "-at_install")
class TestPrivateFacetIdentity(TransactionCase):
    """Gender, birthdate, nationality and the private channels are the private
    facet's, not columns on the employee."""

    def test_create_lands_on_the_facet(self):
        employee = self.env["hr.employee"].create(
            {
                "name": "Facet",
                "sex": "female",
                "birthday": "1990-04-05",
                "country_id": self.env.ref("base.mx").id,
                "private_email": "home@example.com",
                "private_phone": "555",
            }
        )
        home = employee.private_address_id
        self.assertEqual(home.parent_id, employee.partner_id)
        self.assertEqual(home.gender, "female")
        self.assertEqual(str(home.birthdate), "1990-04-05")
        self.assertEqual(home.nationality_id, self.env.ref("base.mx"))
        self.assertEqual(home.email, "home@example.com")
        self.assertEqual(home.phone, "555")
        self.assertEqual(employee.sex, "female")
        self.assertEqual(str(employee.birthday), "1990-04-05")

    def test_write_goes_through_and_reads_back(self):
        employee = self.env["hr.employee"].create({"name": "Facet Later"})
        employee.write({"sex": "other", "birthday": "1980-01-31"})
        self.assertEqual(employee.private_address_id.gender, "other")
        employee.private_address_id.birthdate = "1981-02-02"
        employee.invalidate_recordset(["birthday"])
        self.assertEqual(str(employee.birthday), "1981-02-02")

    def test_the_party_row_carries_none_of_it(self):
        employee = self.env["hr.employee"].create(
            {"name": "Facet Party", "sex": "male", "birthday": "1975-06-06"}
        )
        contact = employee.partner_id
        self.assertFalse(contact.gender)
        self.assertFalse(contact.birthdate)

    def test_a_colleague_cannot_read_it_through_the_employee(self):
        employee = self.env["hr.employee"].create(
            {"name": "Facet Hidden", "sex": "female", "birthday": "1990-04-05"}
        )
        colleague = mail_new_test_user(
            self.env, login="facet_colleague", groups="base.group_user"
        )
        with self.assertRaises(AccessError):
            employee.with_user(colleague).read(["sex"])
        with self.assertRaises(AccessError):
            employee.with_user(colleague).read(["birthday"])

    def test_a_new_record_reads_its_origin_facet(self):
        employee = self.env["hr.employee"].create(
            {"name": "Facet Origin", "private_email": "home@example.com"}
        )
        fresh = employee.new(origin=employee)
        self.assertEqual(fresh.private_address_id, employee.private_address_id)
        self.assertEqual(fresh.private_email, "home@example.com")


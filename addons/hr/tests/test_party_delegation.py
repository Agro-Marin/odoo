from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPartyDelegation(TransactionCase):
    """hr.employee _inherits res.partner: the work contact is the person."""

    def test_an_employee_created_bare_gets_a_party_carrying_its_name(self):
        employee = self.env["hr.employee"].create(
            {"name": "Party Bare", "work_email": "bare@example.com"}
        )
        self.assertTrue(employee.partner_id)
        self.assertEqual(employee.partner_id.name, "Party Bare")
        self.assertEqual(employee.email, "bare@example.com")
        self.assertEqual(employee.resource_id.name, "Party Bare")

    def test_a_rename_reaches_the_party_and_the_resource(self):
        employee = self.env["hr.employee"].create({"name": "Party Before"})
        employee.name = "Party After"
        self.assertEqual(employee.partner_id.name, "Party After")
        self.assertEqual(employee.resource_id.name, "Party After")

    def test_the_party_name_reads_back_through_the_employee(self):
        employee = self.env["hr.employee"].create({"name": "Party Read"})
        employee.partner_id.name = "Party Renamed Elsewhere"
        employee.invalidate_recordset(["name"])
        self.assertEqual(employee.name, "Party Renamed Elsewhere")

    def test_the_avatar_lives_on_the_party_only(self):
        employee = self.env["hr.employee"].create({"name": "Party Avatar"})
        self.assertTrue(employee.partner_id.image_1920)
        self.assertEqual(employee.image_1920, employee.partner_id.image_1920)
        self.env.cr.execute(
            "SELECT count(*) FROM ir_attachment"
            " WHERE res_model = 'hr.employee' AND res_id = %s AND res_field LIKE 'image_%%'",
            (employee.id,),
        )
        self.assertEqual(self.env.cr.fetchone()[0], 0)

    def test_linking_a_user_leaves_a_squatter_with_a_fresh_party(self):
        user = self.env["res.users"].create(
            {"name": "Party User", "login": "party_user"}
        )
        squatter = self.env["hr.employee"].create(
            {"name": "Party Squatter", "partner_id": user.partner_id.id}
        )
        owner = self.env["hr.employee"].create(
            {"name": "Party Owner", "user_id": user.id}
        )
        self.assertEqual(owner.partner_id, user.partner_id)
        self.assertTrue(squatter.partner_id)
        self.assertNotEqual(squatter.partner_id, user.partner_id)
        self.assertEqual(squatter.partner_id.name, "Party Squatter")

    def test_a_user_rename_reaches_the_employee_without_a_sync(self):
        user = self.env["res.users"].create(
            {"name": "Party Login", "login": "party_login"}
        )
        employee = self.env["hr.employee"].create(
            {"name": "Party Login", "user_id": user.id}
        )
        user.name = "Party Login Renamed"
        employee.invalidate_recordset(["name"])
        self.assertEqual(employee.name, "Party Login Renamed")

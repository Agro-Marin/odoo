from odoo.tests.common import tagged, users

from odoo.addons.crm.tests import common as crm_common


@tagged("lead_manage")
class TestLeadConvertToTicket(crm_common.TestCrmCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.lead_1.write(
            {
                "user_id": cls.user_sales_salesman.id,
            }
        )

    @users("user_sales_salesman")
    def test_lead_convert_to_quotation_create(self):
        lead = self.lead_1.with_user(self.env.user)
        self.assertEqual(lead.partner_id, self.env["res.partner"])
        new_partner = self.env["res.partner"].search(
            [("email_normalized", "=", "amy.wong@test.example.com")]
        )
        self.assertEqual(new_partner, self.env["res.partner"])

        convert = (
            self.env["crm.quotation.partner"]
            .with_context({"active_model": "crm.lead", "active_id": lead.id})
            .create({})
        )

        self.assertEqual(convert.action, "create")
        self.assertEqual(convert.partner_id, self.env["res.partner"])

        action = convert.action_apply()

        new_partner = self.env["res.partner"].search(
            [("email_normalized", "=", "amy.wong@test.example.com")]
        )
        self.assertEqual(lead.partner_id, new_partner)

        self.assertEqual(action["res_model"], "sale.order")
        self.assertEqual(action["context"]["default_partner_id"], new_partner.id)

    @users("user_sales_salesman")
    def test_lead_convert_to_quotation_exist(self):
        lead = self.lead_1.with_user(self.env.user)

        convert = (
            self.env["crm.quotation.partner"]
            .with_context({"active_model": "crm.lead", "active_id": lead.id})
            .create({"action": "exist"})
        )

        self.assertEqual(convert.action, "exist")
        self.assertEqual(convert.partner_id, self.env["res.partner"])

        action = convert.action_apply()

        new_partner = self.env["res.partner"].search(
            [("email_normalized", "=", "amy.wong@test.example.com")]
        )
        self.assertEqual(new_partner, self.env["res.partner"])

        convert.write({"partner_id": self.contact_2.id})
        action = convert.action_apply()

        new_partner = self.env["res.partner"].search(
            [("email_normalized", "=", "amy.wong@test.example.com")]
        )
        self.assertEqual(new_partner, self.env["res.partner"])
        self.assertEqual(lead.partner_id, self.contact_2)
        self.assertEqual(lead.email_from, self.contact_2.email)
        self.assertEqual(action["context"]["default_partner_id"], self.contact_2.id)

    @users("user_sales_salesman")
    def test_lead_convert_to_quotation_false_match_create(self):
        lead = self.lead_1.with_user(self.env.user)

        convert = (
            self.env["crm.quotation.partner"]
            .with_context(
                {
                    "active_model": "crm.lead",
                    "active_id": lead.id,
                }
            )
            .create({"action": "create"})
        )

        convert.write({"partner_id": self.contact_2.id})

        self.assertEqual(convert.action, "create")

        convert.action_apply()

        self.assertTrue(bool(lead.partner_id.id))
        self.assertNotEqual(lead.partner_id, self.contact_2)

    @users("user_sales_salesman")
    def test_lead_convert_to_quotation_nothing(self):
        lead = self.lead_1.with_user(self.env.user)

        convert = (
            self.env["crm.quotation.partner"]
            .with_context(
                {
                    "active_model": "crm.lead",
                    "active_id": lead.id,
                    "default_action": "nothing",
                }
            )
            .create({})
        )

        self.assertEqual(convert.action, "nothing")
        self.assertEqual(convert.partner_id, self.env["res.partner"])

        action = convert.action_apply()

        new_partner = self.env["res.partner"].search(
            [("email_normalized", "=", "amy.wong@test.example.com")]
        )
        self.assertEqual(new_partner, self.env["res.partner"])
        self.assertEqual(lead.partner_id, self.env["res.partner"])
        self.assertEqual(action["context"]["default_partner_id"], False)

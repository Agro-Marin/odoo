from odoo.fields import Command
from odoo.tests.common import TransactionCase, tagged


@tagged("web_unit", "web_settings")
class TestResConfigSettings(TransactionCase):
    def setUp(self):
        super().setUp()
        self.user = self.env.ref("base.user_admin")
        self.company = self.env["res.company"].create({"name": "oobO"})
        self.user.write(
            {
                "company_ids": [Command.link(self.company.id)],
                "company_id": self.company.id,
            }
        )
        Settings = self.env["res.config.settings"].with_user(self.user.id)
        self.config = Settings.create({})

    def test_multi_company_res_config_group(self):
        company = self.env["res.company"].create({"name": "My Last Company"})
        partner = self.env["res.partner"].create({"name": "My User"})
        user = self.env["res.users"].create(
            {
                "login": "My User",
                "company_id": company.id,
                "company_ids": [Command.link(company.id)],
                "partner_id": partner.id,
            }
        )

        ResConfig = self.env["res.config.settings"]
        default_values = ResConfig.default_get(list(ResConfig.fields_get()))

        default_values.update({"group_multi_currency": True})
        ResConfig.create(default_values).execute()
        self.assertIn(
            user, self.env.ref("base.group_multi_currency").sudo().all_user_ids
        )

        new_partner = self.env["res.partner"].create({"name": "New User"})
        new_user = self.env["res.users"].create(
            {
                "login": "My First New User",
                "company_id": company.id,
                "company_ids": [Command.link(company.id)],
                "partner_id": new_partner.id,
            }
        )
        self.assertIn(
            new_user,
            self.env.ref("base.group_multi_currency").sudo().all_user_ids,
        )

        default_values.update({"group_multi_currency": False})
        ResConfig.create(default_values).execute()
        self.assertNotIn(
            user, self.env.ref("base.group_multi_currency").sudo().all_user_ids
        )

        new_partner = self.env["res.partner"].create({"name": "New User 2"})
        new_user = self.env["res.users"].create(
            {
                "login": "My Second New User",
                "company_id": company.id,
                "company_ids": [Command.link(company.id)],
                "partner_id": new_partner.id,
            }
        )
        self.assertNotIn(
            new_user,
            self.env.ref("base.group_multi_currency").sudo().all_user_ids,
        )

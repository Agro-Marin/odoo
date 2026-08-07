import odoo.tests
from odoo import Command


@odoo.tests.tagged("-at_install", "post_install")
class TestAccess(odoo.tests.HttpCase):
    def setUp(self):
        super().setUp()

        self.portal_user = self.env["res.users"].create(
            {
                "login": "P",
                "name": "P",
                "group_ids": [Command.set([self.env.ref("base.group_portal").id])],
            }
        )
        self.internal_user_partner = self.env["res.partner"].create({"name": "I"})

        self.document = self.env["test_access_right.ticket"].create(
            {
                "name": "Need help here",
                "message_partner_ids": [
                    Command.set(
                        [
                            self.portal_user.partner_id.id,
                            self.internal_user_partner.id,
                        ]
                    )
                ],
            }
        )

    def test_check_access(self):
        document = self.document.with_user(self.portal_user)
        self.internal_user_partner.invalidate_model(["active"])
        document.check_access("read")

    def test_name_search_with_sudo(self):
        no_access_user = self.env["res.users"].create(
            {
                "login": "no_access",
                "name": "no_access",
                "group_ids": [Command.clear()],
            }
        )
        document = self.env["test_access_right.ticket"].with_user(no_access_user)
        res = document.sudo().name_search("Need help here")
        self.assertEqual(res[0][1], "Need help here")

import odoo.tests


@odoo.tests.tagged("post_install", "-at_install")
class TestCrmTeamMemberTour(odoo.tests.HttpCase):
    """The Team Members list shows each salesperson's avatar.

    A HOOT test cannot cover this: its mock server has no access to our view
    files, so the arch comes from the test itself and the assertion would hold
    before the change as well. Only a browser run against the real action reads
    the view we actually ship.
    """

    def test_member_list_shows_the_salesperson_avatar(self):
        user = self.env["res.users"].create(
            {
                "name": "Avatar Salesperson",
                "login": "avatar_salesperson",
                "group_ids": [
                    (6, 0, [self.env.ref("sales_team.group_sale_salesman").id])
                ],
            }
        )
        team = self.env["crm.team"].create({"name": "Avatar Team", "company_id": False})
        self.env["crm.team.member"].create({"crm_team_id": team.id, "user_id": user.id})
        self.env.flush_all()

        self.start_tour(
            "/odoo",
            "crm_team_member_list_avatar",
            login="admin",
        )

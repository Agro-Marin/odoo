from odoo import Command
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestTeamDocumentsReadTheRecordsTeam(TransactionCase):
    # "Team Documents" reaches the orders of the salesman's teams: the order's
    # own team, whoever sold it, or an order nobody sold (the user's decision,
    # P4 T2 option B), no longer the orders of whoever shares a team with them

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].set_param("sale_team.membership_multi", True)
        Team = cls.env["team.team"]
        cls.team_a = Team.create({"name": "A", "use_sale": True})
        cls.team_b = Team.create({"name": "B", "use_sale": True})
        Users = cls.env["res.users"]
        cls.salesman = Users.create(
            {
                "login": "team_documents",
                "name": "Team documents",
                "group_ids": [
                    Command.set(cls.env.ref("sale.group_sale_salesman_team").ids)
                ],
            }
        )
        cls.colleague = Users.create({"login": "colleague", "name": "Colleague"})
        cls.outsider = Users.create({"login": "outsider", "name": "Outsider"})
        Member = cls.env["team.member"]
        Member.create({"team_id": cls.team_a.id, "user_id": cls.salesman.id})
        Member.create({"team_id": cls.team_a.id, "user_id": cls.colleague.id})
        Member.create({"team_id": cls.team_b.id, "user_id": cls.colleague.id})
        partner = cls.env["res.partner"].create({"name": "Customer"})
        Order = cls.env["sale.order"]

        def order(user, team):
            return Order.create(
                {
                    "partner_id": partner.id,
                    "user_id": user.id if user else False,
                    "team_id": team.id if team else False,
                }
            )

        cls.a_by_outsider = order(cls.outsider, cls.team_a)
        cls.b_by_colleague = order(cls.colleague, cls.team_b)
        cls.unsold = order(None, cls.team_b)
        cls.orders = cls.a_by_outsider + cls.b_by_colleague + cls.unsold

    def test_the_order_s_team_decides_not_the_seller_s(self):
        reached = (
            self.env["sale.order"]
            .with_user(self.salesman)
            .search([("id", "in", self.orders.ids)])
        )
        self.assertEqual(reached, self.a_by_outsider + self.unsold)

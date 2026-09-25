from odoo import Command
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestTeamAccessBind(TransactionCase):
    # a team rung compares the record's team with the principal's teams; the
    # bind reads them as res.users' team_ids and <usage>_team_ids do

    def test_the_teams_are_those_the_user_fields_read(self):
        for usage in ("alpha", "beta"):
            self.env["ir.config_parameter"].set_param(
                f"test_team.{usage}_membership_multi", True
            )
        Team = self.env["team.team"]
        alpha = Team.create({"name": "Alpha", "use_alpha": True})
        beta = Team.create({"name": "Beta", "use_beta": True})
        left = Team.create({"name": "Left", "use_alpha": True})
        led = Team.create({"name": "Led", "use_alpha": True})
        user = self.env["res.users"].create(
            {
                "login": "binder",
                "name": "Binder",
                "group_ids": [Command.set(self.env.ref("base.group_user").ids)],
            }
        )
        Member = self.env["team.member"]
        Member.create(
            [{"team_id": team.id, "user_id": user.id} for team in (alpha, beta)]
        )
        Member.create({"team_id": left.id, "user_id": user.id}).action_archive()
        led.user_id = user
        access = self.env["ir.access"].with_user(user)
        self.assertEqual(access._access_bind_teams(None), user.team_ids.ids)
        self.assertEqual(access._access_bind_teams(None), sorted((alpha + beta).ids))
        self.assertEqual(access._access_bind_teams("alpha"), user.alpha_team_ids.ids)
        self.assertEqual(access._access_bind_teams("beta"), beta.ids)

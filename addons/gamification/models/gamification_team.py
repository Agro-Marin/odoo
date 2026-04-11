from odoo import api, fields, models


class GamificationTeam(models.Model):
    """Team for collaborative gamification challenges.

    Teams aggregate individual member performance into a team score.
    They can be manually composed or auto-populated from an HR department.
    Team-vs-team competition increases engagement for all participants —
    collaboration within a team offsets the demotivation that individual
    leaderboards cause for the bottom 80% of performers.
    """

    _name = "gamification.team"
    _description = "Gamification Team"
    _inherit = ["mail.thread"]
    _order = "name"

    name = fields.Char("Team Name", required=True, translate=True, tracking=True)
    description = fields.Text("Description", translate=True)
    active = fields.Boolean(default=True)
    image_128 = fields.Image("Avatar", max_width=128, max_height=128)

    member_ids = fields.Many2many(
        "res.users",
        "gamification_team_members_rel",
        string="Members",
    )
    captain_id = fields.Many2one(
        "res.users",
        string="Captain",
        help="Team leader who receives challenge reports.",
    )
    member_count = fields.Integer("# Members", compute="_compute_member_count")

    # Computed team stats
    team_karma = fields.Integer(
        "Team Karma",
        compute="_compute_team_stats",
        store=True,
        help="Sum of all members' karma.",
    )
    team_badges = fields.Integer(
        "Team Badges",
        compute="_compute_team_stats",
        store=True,
        help="Total badges earned by all team members.",
    )

    challenge_ids = fields.Many2many(
        "gamification.challenge",
        "gamification_challenge_team_rel",
        string="Active Challenges",
    )

    @api.depends("member_ids")
    def _compute_member_count(self) -> None:
        """Count members per team."""
        for team in self:
            team.member_count = len(team.member_ids)

    @api.depends("member_ids.karma", "member_ids.badge_ids")
    def _compute_team_stats(self) -> None:
        """Compute aggregate karma and badge counts from members."""
        for team in self:
            members = team.member_ids
            team.team_karma = sum(members.mapped("karma"))
            team.team_badges = (
                self.env["gamification.badge.user"].search_count(
                    [
                        ("user_id", "in", members.ids),
                    ]
                )
                if members
                else 0
            )

    def get_team_challenge_score(self, challenge) -> float:
        """Compute this team's score for a given challenge.

        The score is the average completeness across all members' goals
        for the **current period** of the challenge, normalized to 0-100%.

        :param challenge: ``gamification.challenge`` record.
        :return: float, average completeness percentage.
        """
        from .gamification_utils import start_end_date_for_period

        self.ensure_one()
        if not self.member_ids:
            return 0.0
        (start_date, end_date) = start_end_date_for_period(
            challenge.period,
            challenge.start_date,
            challenge.end_date,
        )
        domain = [
            ("challenge_id", "=", challenge.id),
            ("user_id", "in", self.member_ids.ids),
            ("state", "!=", "draft"),
        ]
        if start_date:
            domain.append(("start_date", "=", start_date))
        if end_date:
            domain.append(("end_date", "=", end_date))
        goals = self.env["gamification.goal"].search(domain)
        if not goals:
            return 0.0
        return sum(goals.mapped("completeness")) / len(goals)

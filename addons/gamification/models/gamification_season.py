from typing import Any

from odoo import _, api, fields, models


class GamificationSeason(models.Model):
    """Time-limited themed gamification event with exclusive rewards.

    Seasons create urgency and novelty (Octalysis drive 6: Scarcity).
    Each season has its own leaderboard that resets, solving the
    "permanent bottom-half" problem of global leaderboards.
    Exclusive badges and challenges are only available during the season.
    """

    _name = "gamification.season"
    _description = "Gamification Season"
    _inherit = ["mail.thread"]
    _order = "start_date desc"

    name = fields.Char("Season Name", required=True, translate=True, tracking=True)
    description = fields.Html(
        "Description",
        translate=True,
        sanitize_attributes=False,
    )
    theme = fields.Char(
        "Theme",
        translate=True,
        help="Visual theme or motto (e.g., 'The Quality Quarter', 'Innovation Sprint').",
    )
    icon = fields.Image("Icon", max_width=128, max_height=128)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("active", "Active"),
            ("ended", "Ended"),
            ("archived", "Archived"),
        ],
        default="draft",
        required=True,
        tracking=True,
        index=True,
    )
    start_date = fields.Date("Start Date", required=True, tracking=True)
    end_date = fields.Date("End Date", required=True, tracking=True)

    # Exclusive content
    challenge_ids = fields.One2many(
        "gamification.challenge",
        "season_id",
        string="Season Challenges",
    )
    badge_ids = fields.Many2many(
        "gamification.badge",
        "gamification_season_badge_rel",
        string="Exclusive Badges",
        help="Badges only available during this season.",
    )
    quest_ids = fields.Many2many(
        "gamification.quest",
        "gamification_season_quest_rel",
        string="Season Quests",
    )

    # Stats
    challenge_count = fields.Integer("# Challenges", compute="_compute_counts")
    participant_count = fields.Integer("# Participants", compute="_compute_counts")

    @api.depends("challenge_ids", "challenge_ids.user_ids")
    def _compute_counts(self):
        for season in self:
            season.challenge_count = len(season.challenge_ids)
            all_users = season.challenge_ids.mapped("user_ids")
            season.participant_count = len(all_users)

    def action_view_challenges(self) -> dict[str, Any]:
        """Navigate to challenges linked to this season."""
        self.ensure_one()
        return {
            "name": _("Season Challenges"),
            "type": "ir.actions.act_window",
            "res_model": "gamification.challenge",
            "view_mode": "list,form",
            "domain": [("season_id", "=", self.id)],
            "context": {"default_season_id": self.id},
        }

    def action_activate(self):
        """Start the season."""
        for season in self.filtered(lambda s: s.state == "draft"):
            season.state = "active"

    def action_end(self):
        """End the season and archive its challenges."""
        for season in self.filtered(lambda s: s.state == "active"):
            season.state = "ended"

    def action_archive(self):
        """Archive a completed season."""
        self.filtered(lambda s: s.state == "ended").write({"state": "archived"})

    def get_season_leaderboard(self, limit=10):
        """Return karma earned during this season's time window.

        Unlike the global leaderboard, this only counts karma gained
        between start_date and end_date — giving everyone a fresh start.

        :param int limit: max entries.
        :return: list of dicts.
        """
        self.ensure_one()
        if not self.start_date or not self.end_date:
            return []

        cr = self.env.cr
        cr.execute(
            """
            SELECT
                u.id AS user_id,
                p.name AS user_name,
                COALESCE(SUM(GREATEST(t.new_value - t.old_value, 0)), 0) AS season_karma
            FROM res_users u
            JOIN res_partner p ON p.id = u.partner_id
            LEFT JOIN gamification_karma_tracking t
                ON t.user_id = u.id
                AND t.tracking_date::date >= %(start)s
                AND t.tracking_date::date <= %(end)s
            WHERE u.active IS TRUE
              AND u.share IS NOT TRUE
              AND u.company_id = %(company_id)s
              AND COALESCE(u.gamification_visibility, 'public') != 'private'
            GROUP BY u.id, p.name
            HAVING COALESCE(SUM(GREATEST(t.new_value - t.old_value, 0)), 0) > 0
            ORDER BY season_karma DESC
            LIMIT %(limit)s
        """,
            {
                "start": self.start_date,
                "end": self.end_date,
                "company_id": self.env.company.id,
                "limit": limit,
            },
        )
        current_uid = self.env.uid
        return [
            {
                "user_id": row["user_id"],
                "user_name": row["user_name"],
                "season_karma": row["season_karma"],
                "is_current_user": row["user_id"] == current_uid,
            }
            for row in cr.dictfetchall()
        ]

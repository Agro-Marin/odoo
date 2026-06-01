from typing import Literal, Self

from odoo import api, fields, models
from odoo.models import ValuesType
from odoo.tools.translate import html_translate


class GamificationKarmaRank(models.Model):
    """Karma-based rank (level) in the gamification progression system.

    Ranks define thresholds in the karma XP curve.  When a user's karma
    crosses a threshold, they level up and optionally receive badges.
    """

    _name = "gamification.karma.rank"
    _description = "Gamification Rank / Level"
    _inherit = ["image.mixin"]
    _order = "karma_min"

    name = fields.Text(string="Rank Name", translate=True, required=True)
    description = fields.Html(
        string="Description",
        translate=html_translate,
        sanitize_attributes=False,
    )
    description_motivational = fields.Html(
        string="Motivational",
        translate=html_translate,
        sanitize_attributes=False,
        sanitize_overridable=True,
        help="Motivational phrase to reach this rank on your profile page.",
    )
    description_perks = fields.Html(
        string="Unlocked Perks",
        translate=html_translate,
        sanitize_attributes=False,
        help="Describe what capabilities or permissions this rank unlocks.",
    )
    karma_min = fields.Integer(string="Required Karma (XP)", required=True, default=1)
    level_number = fields.Integer(
        string="Level",
        default=0,
        help="Sequential level number for display (1, 2, 3, ...). "
        "Set to 0 for auto-ordering by karma_min.",
    )
    unlock_badge_ids = fields.Many2many(
        "gamification.badge",
        string="Auto-Grant Badges",
        help="Badges automatically granted when a user reaches this rank.",
    )
    user_ids = fields.One2many("res.users", "rank_id", string="Users")
    rank_users_count = fields.Integer("# Users", compute="_compute_rank_users_count")

    _karma_min_check = models.Constraint(
        "CHECK( karma_min > 0 )",
        "The required karma has to be above 0.",
    )

    @api.depends("user_ids")
    def _compute_rank_users_count(self) -> None:
        requests_data = self.env["res.users"]._read_group(
            [("rank_id", "!=", False)], ["rank_id"], ["__count"]
        )
        requests_mapped_data = {rank.id: count for rank, count in requests_data}
        for rank in self:
            rank.rank_users_count = requests_mapped_data.get(rank.id, 0)

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        res = super().create(vals_list)
        if any(k > 0 for k in res.mapped("karma_min")):
            users = (
                self.env["res.users"]
                .sudo()
                .search([("karma", ">=", max(min(res.mapped("karma_min")), 1))])
            )
            if users:
                users._recompute_rank()
        return res

    def write(self, vals: ValuesType) -> Literal[True]:
        if "karma_min" in vals:
            previous_ranks = (
                self.env["gamification.karma.rank"]
                .search([], order="karma_min DESC")
                .ids
            )
            low = min(vals["karma_min"], *self.mapped("karma_min"))
            high = max(vals["karma_min"], *self.mapped("karma_min"))

        res = super().write(vals)

        if "karma_min" in vals:
            after_ranks = (
                self.env["gamification.karma.rank"]
                .search([], order="karma_min DESC")
                .ids
            )
            if previous_ranks != after_ranks:
                users = (
                    self.env["res.users"].sudo().search([("karma", ">=", max(low, 1))])
                )
            else:
                users = (
                    self.env["res.users"]
                    .sudo()
                    .search([("karma", ">=", max(low, 1)), ("karma", "<=", high)])
                )
            users._recompute_rank()
        return res

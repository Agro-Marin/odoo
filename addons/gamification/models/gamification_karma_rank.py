from typing import Literal, Self

from odoo import api, fields, models
from odoo.models import ValuesType
from odoo.tools.translate import html_translate


# Ranks define thresholds in the karma XP curve.  When a user's karma
# crosses a threshold, they level up and optionally receive badges.
class GamificationKarmaRank(models.Model):
    """Karma-based rank (level) in the gamification progression system."""

    _name = "gamification.karma.rank"
    _description = "Gamification Rank / Level"
    _inherit = ["mixin.image"]
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
    rank_users_count = fields.Count("user_ids", "# Users")

    _karma_min_check = models.Constraint(
        "CHECK( karma_min > 0 )",
        "The required karma has to be above 0.",
    )

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
            # `min(x, *[])` is `min(int)`, which raises TypeError: writing
            # karma_min on an empty recordset is legal and used to blow up here.
            thresholds = [vals["karma_min"], *self.mapped("karma_min")]
            low, high = min(thresholds), max(thresholds)

        res = super().write(vals)

        if "karma_min" in vals:
            after_ranks = (
                self.env["gamification.karma.rank"]
                .search([], order="karma_min DESC")
                .ids
            )
            if previous_ranks != after_ranks:
                # Order changed: any ranked user can move, including one at
                # karma 0 still holding a rank that `karma >= low` never selects.
                users = (
                    self.env["res.users"]
                    .sudo()
                    .search(
                        [
                            "|",
                            ("karma", ">=", max(low, 1)),
                            ("rank_id", "!=", False),
                        ]
                    )
                )
            else:
                users = (
                    self.env["res.users"]
                    .sudo()
                    .search([("karma", ">=", max(low, 1)), ("karma", "<=", high)])
                )
            users._recompute_rank()
        return res

    def _can_return_content(
        self, field_name: str | None = None, access_token: str | None = None
    ) -> bool:
        """Serve the rank pictures to visitors that hold no ACL on this model.

        A profile page renders the rank as ``t-field="rank_id.image_1920"``,
        which the browser resolves to ``/web/image/gamification.karma.rank/<id>/
        image_128``. The page itself was rendered from a sudo recordset, but
        that image request arrives as the portal or public visitor, and
        ``ir.binary`` falls back to ``check_access("read")`` for anyone this
        hook turns down.

        The images are the only thing an external audience needs from a rank,
        so they are opened here instead of by handing the whole model back an
        ACL. Only the fields the image mixin defines qualify; anything else
        keeps going through the access check.
        """
        if isinstance(self.env["mixin.image"]._fields.get(field_name), fields.Image):
            return True
        return super()._can_return_content(field_name, access_token)

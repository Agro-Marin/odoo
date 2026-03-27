import logging

from odoo import _, api, fields, models
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)


class GamificationAchievement(models.Model):
    """Hidden/discovery achievement that users unlock through normal work.

    Unlike challenges (which are explicitly assigned), achievements are
    *discovered* when the user's activity matches a trigger condition.
    Hidden achievements add a layer of surprise and delight — Octalysis
    core drive #7 (Unpredictability & Curiosity).
    """

    _name = "gamification.achievement"
    _description = "Gamification Achievement"
    _order = "sequence, name"

    name = fields.Char("Achievement", required=True, translate=True)
    description = fields.Text(
        "Description",
        translate=True,
        help="Shown after the achievement is unlocked.",
    )
    hint = fields.Text(
        "Hint",
        translate=True,
        help="Optional hint shown before unlock. Leave empty for full mystery.",
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    icon = fields.Image("Icon", max_width=128, max_height=128)

    # Trigger configuration
    model_id = fields.Many2one(
        "ir.model",
        string="Trigger Model",
        required=True,
        ondelete="cascade",
        help="The model to evaluate for this achievement.",
    )
    trigger_domain = fields.Char(
        "Trigger Domain",
        required=True,
        default="[]",
        help="Domain evaluated per user. May reference 'user'. "
        "Achievement unlocks when at least one record matches.",
    )
    trigger_count = fields.Integer(
        "Required Count",
        default=1,
        help="Number of records that must match the domain to unlock. "
        "Use 1 for simple presence checks, higher for cumulative achievements.",
    )

    # Rewards
    badge_id = fields.Many2one(
        "gamification.badge",
        string="Reward Badge",
        help="Badge automatically granted when the achievement is unlocked.",
    )
    karma_reward = fields.Integer(
        "Karma Reward",
        default=0,
        help="Karma points granted on unlock.",
    )
    rarity = fields.Selection(
        [
            ("common", "Common"),
            ("rare", "Rare"),
            ("epic", "Epic"),
            ("legendary", "Legendary"),
        ],
        default="common",
        required=True,
        string="Rarity",
    )
    hidden = fields.Boolean(
        "Mystery Achievement",
        default=True,
        help="If checked, the achievement name and description are hidden "
        "until unlocked. Only the hint (if any) is visible.",
    )

    # Tracking
    unlock_ids = fields.One2many(
        "gamification.achievement.unlock",
        "achievement_id",
        string="Unlocks",
    )
    unlock_count = fields.Integer("# Unlocked", compute="_compute_unlock_count")

    @api.depends("unlock_ids")
    def _compute_unlock_count(self) -> None:
        """Count how many users have unlocked this achievement."""
        if not self.ids:
            for rec in self:
                rec.unlock_count = 0
            return
        data = self.env["gamification.achievement.unlock"]._read_group(
            [("achievement_id", "in", self.ids)],
            groupby=["achievement_id"],
            aggregates=["__count"],
        )
        count_map = {ach.id: count for ach, count in data}
        for rec in self:
            rec.unlock_count = count_map.get(rec.id, 0)

    def _check_achievement_for_users(
        self,
        users: models.Model | None = None,
    ) -> models.Model:
        """Evaluate this achievement's trigger for a set of users.

        :param users: ``res.users`` recordset to check.  If ``None``,
            checks all active internal users.
        :return: recordset of newly unlocked ``gamification.achievement.unlock``.
        """
        self.ensure_one()
        if users is None:
            users = self.env["res.users"].search(
                [
                    ("active", "=", True),
                    ("share", "=", False),
                ]
            )

        Unlock = self.env["gamification.achievement.unlock"]
        # Find users who already have this achievement
        already_unlocked = Unlock.search(
            [
                ("achievement_id", "=", self.id),
                ("user_id", "in", users.ids),
            ]
        ).mapped("user_id")
        candidates = users - already_unlocked
        if not candidates:
            return Unlock.browse()

        Obj = self.env[self.model_id.model].sudo()
        new_unlocks = Unlock.browse()

        for user in candidates:
            domain = safe_eval(self.trigger_domain, {"user": user})
            count = Obj.search_count(domain)
            if count >= self.trigger_count:
                new_unlocks |= Unlock.create(
                    {
                        "achievement_id": self.id,
                        "user_id": user.id,
                    }
                )
                _logger.info(
                    "Achievement unlocked: '%s' for user %s",
                    self.name,
                    user.login,
                )

        return new_unlocks

    @api.model
    def _cron_check_achievements(self) -> None:
        """Daily cron: evaluate all active achievements for all users.

        Processes each achievement and grants rewards for new unlocks.
        """
        achievements = self.search([("active", "=", True)])
        for achievement in achievements:
            new_unlocks = achievement._check_achievement_for_users()
            for unlock in new_unlocks:
                unlock._grant_rewards()


class GamificationAchievementUnlock(models.Model):
    """Record of a user unlocking an achievement."""

    _name = "gamification.achievement.unlock"
    _description = "Achievement Unlock"
    _order = "unlock_date desc"
    _rec_name = "achievement_id"

    achievement_id = fields.Many2one(
        "gamification.achievement",
        string="Achievement",
        required=True,
        index=True,
        ondelete="cascade",
    )
    user_id = fields.Many2one(
        "res.users",
        string="User",
        required=True,
        index=True,
        ondelete="cascade",
    )
    unlock_date = fields.Datetime(
        "Unlocked On",
        default=fields.Datetime.now,
        readonly=True,
    )

    # Denormalized for display
    rarity = fields.Selection(
        related="achievement_id.rarity", store=True, readonly=True
    )
    achievement_name = fields.Char(
        string="Achievement Name", related="achievement_id.name", readonly=True
    )

    _user_achievement_uniq = models.UniqueIndex(
        "(user_id, achievement_id)",
        "A user can only unlock an achievement once.",
    )

    def _grant_rewards(self) -> None:
        """Grant badge and karma rewards for this unlock."""
        for unlock in self:
            achievement = unlock.achievement_id
            user = unlock.user_id

            # Grant karma
            if achievement.karma_reward:
                user.sudo()._add_karma(
                    achievement.karma_reward,
                    source=unlock,
                    reason=_("Achievement: %s", achievement.name),
                )

            # Grant badge
            if achievement.badge_id:
                self.env["gamification.badge.user"].sudo().create(
                    {
                        "user_id": user.id,
                        "badge_id": achievement.badge_id.id,
                    }
                )._send_badge()

            # Bus notification
            user._send_gamification_notification(
                "achievement",
                {
                    "title": _("Achievement Unlocked!"),
                    "message": achievement.name,
                    "rarity": achievement.rarity,
                },
            )
            # Log to unified activity feed
            self.env["gamification.activity"]._log_achievement(
                user,
                achievement,
                achievement.karma_reward,
            )

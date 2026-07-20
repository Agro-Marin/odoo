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
        # safe_eval references 'user' per candidate so each domain is unique —
        # it cannot be collapsed into a single query.  But the per-user count
        # only needs to know whether the threshold is *reached*, so it is
        # capped at ``trigger_count``: for the default ``trigger_count = 1`` the
        # database stops at the first matching row instead of scanning every
        # row the user owns (a full COUNT(*) over e.g. account.move.line).  The
        # unlock creation is batched into one INSERT.
        trigger_count = max(self.trigger_count, 1)
        unlock_vals = []
        for user in candidates:
            domain = safe_eval(self.trigger_domain, {"user": user})
            count = Obj.search_count(domain, limit=trigger_count)
            if count >= trigger_count:
                unlock_vals.append(
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

        return Unlock.create(unlock_vals) if unlock_vals else Unlock.browse()

    @api.model
    def _cron_check_achievements(self) -> None:
        """Daily cron: evaluate all active achievements for all users.

        Processes each achievement and grants rewards for new unlocks.
        """
        achievements = self.search([("active", "=", True)])
        for achievement in achievements:
            # Isolate each achievement in a savepoint.  A single malformed
            # ``trigger_domain`` (bad syntax, or a field dropped by a module
            # upgrade) otherwise raised out of the cron, rolling back every
            # achievement already processed in this run.  Because ``_order`` is
            # stable, the same poison record blocked the same achievements on
            # every subsequent night, silently and indefinitely.
            try:
                with self.env.cr.savepoint():
                    new_unlocks = achievement._check_achievement_for_users()
                    for unlock in new_unlocks:
                        unlock._grant_rewards()
            except Exception:
                _logger.exception(
                    "Achievement %r (id %s) failed to evaluate; skipping it "
                    "and continuing the run.",
                    achievement.name,
                    achievement.id,
                )


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
        """Grant badge and karma rewards for a batch of unlocks.

        Karma is granted through ``_add_karma_batch`` and badges through a
        single ``create`` per achievement, instead of one INSERT +
        ``_compute_karma`` + ``_recompute_rank`` cycle per unlock.  With the
        daily cron unlocking many users at once this is the difference between
        O(unlocks) and O(distinct achievements) write cycles.
        """
        Users = self.env["res.users"].sudo()
        BadgeUser = self.env["gamification.badge.user"].sudo()
        Activity = self.env["gamification.activity"]

        # Group by achievement: karma source/reason and the badge differ per
        # achievement, and within one achievement the (user, achievement)
        # unique index guarantees users are distinct, so a per-user dict cannot
        # collide.  Karma and badges are batched (one write cycle per
        # achievement instead of per unlock); the bus notification and activity
        # log stay per user because each targets that user's own feed.
        badge_vals = []
        for achievement, unlocks in self.grouped("achievement_id").items():
            if achievement.karma_reward:
                Users._add_karma_batch(
                    {
                        unlock.user_id: {
                            "gain": achievement.karma_reward,
                            "source": unlock,
                            "reason": _("Achievement: %s", achievement.name),
                        }
                        for unlock in unlocks
                    }
                )
            if achievement.badge_id:
                badge_vals += [
                    {
                        "user_id": unlock.user_id.id,
                        "badge_id": achievement.badge_id.id,
                    }
                    for unlock in unlocks
                ]

            for unlock in unlocks:
                unlock.user_id._send_gamification_notification(
                    "achievement",
                    {
                        "title": _("Achievement Unlocked!"),
                        "message": achievement.name,
                        "rarity": achievement.rarity,
                    },
                )
                Activity._log_achievement(
                    unlock.user_id,
                    achievement,
                    achievement.karma_reward,
                )

        if badge_vals:
            BadgeUser.create(badge_vals)._send_badge()

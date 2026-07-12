from odoo import _, api, fields, models


class GamificationActivity(models.Model):
    """Centralized social activity feed for gamification events.

    Aggregates all notable gamification events into a single, time-ordered
    stream.  This powers the company-wide social feed on the dashboard
    and provides the visibility that drives Socializer player types.

    Activities are auto-created by source models (badges, kudos,
    achievements, streaks, rank-ups) via helper methods — never manually.
    Inherits mail.thread so users can react to or discuss activities.
    """

    _name = "gamification.activity"
    _description = "Gamification Activity Feed"
    _inherit = ["mail.thread"]
    _order = "activity_date desc, id desc"
    _rec_name = "summary"

    activity_type = fields.Selection(
        [
            ("badge", "Badge Earned"),
            ("kudos", "Kudos Sent"),
            ("achievement", "Achievement Unlocked"),
            ("streak_milestone", "Streak Milestone"),
            ("level_up", "Level Up"),
            ("challenge_completed", "Challenge Completed"),
            ("quest_completed", "Quest Completed"),
            ("skill_unlocked", "Skill Unlocked"),
        ],
        string="Type",
        required=True,
        readonly=True,
        index=True,
    )
    user_id = fields.Many2one(
        "res.users",
        string="User",
        required=True,
        index=True,
        ondelete="cascade",
        readonly=True,
    )
    target_user_id = fields.Many2one(
        "res.users",
        string="Target User",
        index=True,
        ondelete="set null",
        readonly=True,
        help="Secondary user (e.g. kudos recipient).",
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        related="user_id.company_id",
        store=True,
        index=True,
    )
    summary = fields.Char("Summary", required=True, readonly=True)
    icon = fields.Char("Icon CSS", readonly=True)
    activity_date = fields.Datetime(
        "Date",
        default=fields.Datetime.now,
        readonly=True,
        index=True,
    )

    # Optional references to source records
    badge_id = fields.Many2one("gamification.badge", ondelete="set null", readonly=True)
    achievement_id = fields.Many2one(
        "gamification.achievement", ondelete="set null", readonly=True
    )
    challenge_id = fields.Many2one(
        "gamification.challenge", ondelete="set null", readonly=True
    )
    karma_gained = fields.Integer("Karma Gained", readonly=True)

    # ── Factory methods (called by source models) ───────────────────

    @api.model
    def _log_badge(self, user, badge, sender=None):
        """Record a badge-earned activity."""
        if sender:
            summary = _(
                "%(sender)s awarded %(badge)s to %(user)s",
                sender=sender.name,
                badge=badge.name,
                user=user.name,
            )
        else:
            summary = _(
                "%(user)s earned the %(badge)s badge",
                user=user.name,
                badge=badge.name,
            )
        return self.sudo().create(
            {
                "activity_type": "badge",
                "user_id": user.id,
                "target_user_id": sender.id if sender else False,
                "summary": summary,
                "icon": "fa fa-certificate",
                "badge_id": badge.id,
            }
        )

    @api.model
    def _log_kudos(self, sender, recipient, category, karma):
        """Record a kudos-sent activity."""
        return self.sudo().create(
            {
                "activity_type": "kudos",
                "user_id": sender.id,
                "target_user_id": recipient.id,
                "summary": _(
                    "%(sender)s recognized %(recipient)s for %(category)s",
                    sender=sender.name,
                    recipient=recipient.name,
                    category=category.name,
                ),
                "icon": category.icon or "fa fa-heart",
                "karma_gained": karma,
            }
        )

    @api.model
    def _log_achievement(self, user, achievement, karma):
        """Record an achievement-unlocked activity."""
        return self.sudo().create(
            {
                "activity_type": "achievement",
                "user_id": user.id,
                "summary": _(
                    "%(user)s unlocked '%(achievement)s' (%(rarity)s)",
                    user=user.name,
                    achievement=achievement.name,
                    rarity=achievement.rarity,
                ),
                "icon": "fa fa-trophy",
                "achievement_id": achievement.id,
                "karma_gained": karma,
            }
        )

    @api.model
    def _log_streak_milestone(self, user, streak_type, day_count, karma):
        """Record a streak milestone activity."""
        return self.sudo().create(
            {
                "activity_type": "streak_milestone",
                "user_id": user.id,
                "summary": _(
                    "%(user)s reached %(days)s days on %(streak)s!",
                    user=user.name,
                    days=day_count,
                    streak=streak_type.name,
                ),
                "icon": "fa fa-fire",
                "karma_gained": karma,
            }
        )

    @api.model
    def _log_level_up(self, user, rank):
        """Record a level-up activity."""
        return self.sudo().create(
            {
                "activity_type": "level_up",
                "user_id": user.id,
                "summary": _(
                    "%(user)s reached %(rank)s!",
                    user=user.name,
                    rank=rank.name,
                ),
                "icon": "fa fa-arrow-up",
            }
        )

    @api.model
    def _log_challenge_completed(self, user, challenge):
        """Record a challenge-completed activity."""
        return self.sudo().create(
            {
                "activity_type": "challenge_completed",
                "user_id": user.id,
                "summary": _(
                    "%(user)s completed the '%(challenge)s' challenge",
                    user=user.name,
                    challenge=challenge.name,
                ),
                "icon": "fa fa-flag-checkered",
                "challenge_id": challenge.id,
            }
        )

    # ── Feed API ────────────────────────────────────────────────────

    @api.model
    def get_activity_feed(self, limit=30):
        """Return the latest activities for the dashboard social feed.

        Filters by the current user's company.  Respects users'
        ``gamification_visibility`` setting — activities from users
        with 'private' visibility are excluded.

        :param int limit: max entries.
        :return: list of dicts for the OWL component.
        """
        # An activity is two-party (e.g. kudos sender ↔ recipient, badge awarder
        # ↔ earner) and its ``summary`` bakes in both names.  Exclude the row if
        # *either* party is private, otherwise a private user still surfaces as
        # the counterparty of a public user's event.
        activities = self.search(
            [
                ("company_id", "=", self.env.company.id),
                ("user_id.gamification_visibility", "!=", "private"),
                "|",
                ("target_user_id", "=", False),
                ("target_user_id.gamification_visibility", "!=", "private"),
            ],
            limit=limit,
        )
        return [
            {
                "id": a.id,
                "activity_type": a.activity_type,
                "user_name": a.user_id.name,
                "target_user_name": a.target_user_id.name
                if a.target_user_id
                else False,
                "summary": a.summary,
                "icon": a.icon,
                "karma_gained": a.karma_gained,
                "date": a.create_date.date().isoformat() if a.create_date else False,
            }
            for a in activities
        ]

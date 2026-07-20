import logging
from datetime import date, datetime, time, timedelta

import pytz

from odoo import _, api, fields, models
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)

# Milestone days and their karma bonus multipliers.
# At day 7 the user gets base_karma * 2, at day 30 base_karma * 5, etc.
STREAK_MILESTONES = {
    7: 2,
    30: 5,
    100: 10,
    365: 25,
}


class GamificationStreakType(models.Model):
    """Configurable streak type defining what activity sustains the streak.

    Each streak type specifies an ORM domain evaluated daily per user.
    If the domain matches at least one record created/modified on the
    previous day, the streak continues; otherwise it breaks.
    """

    _name = "gamification.streak.type"
    _description = "Gamification Streak Type"
    _order = "sequence, name"

    name = fields.Char("Streak Name", required=True, translate=True)
    description = fields.Text("Description", translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    icon = fields.Image("Icon", max_width=128, max_height=128)

    # What counts as "activity" for this streak
    model_id = fields.Many2one(
        "ir.model",
        string="Target Model",
        required=True,
        ondelete="cascade",
        help="The model where activity is tracked (e.g. crm.lead, account.move).",
    )
    domain = fields.Char(
        "Activity Domain",
        required=True,
        default="[]",
        help="Domain to filter records.  May reference 'user' (current user) "
        "and 'date_from' / 'date_to' (the day being checked).",
    )
    date_field_id = fields.Many2one(
        "ir.model.fields",
        string="Date Field",
        required=True,
        ondelete="cascade",
        help="The date/datetime field used to check daily activity.",
    )

    # Rewards
    karma_bonus = fields.Integer(
        "Daily Karma Bonus",
        default=0,
        help="Karma granted each day the streak is maintained.  "
        "Milestone days (7, 30, 100, 365) multiply this value.",
    )
    freeze_allowance = fields.Integer(
        "Freeze Days per Month",
        default=2,
        help="Number of days per month a user can skip without breaking the streak.",
    )

    streak_ids = fields.One2many(
        "gamification.streak", "streak_type_id", string="User Streaks"
    )
    user_count = fields.Integer("# Active Streaks", compute="_compute_user_count")

    @api.depends("streak_ids.state")
    def _compute_user_count(self) -> None:
        """Count active streaks per type."""
        if not self.ids:
            for rec in self:
                rec.user_count = 0
            return
        data = self.env["gamification.streak"]._read_group(
            [("streak_type_id", "in", self.ids), ("state", "=", "active")],
            groupby=["streak_type_id"],
            aggregates=["__count"],
        )
        count_map = {st.id: count for st, count in data}
        for rec in self:
            rec.user_count = count_map.get(rec.id, 0)

    def _check_user_activity(self, user: models.Model, check_date: date) -> bool:
        """Check if *user* performed the required activity on *check_date*.

        :param user: ``res.users`` record.
        :param check_date: ``date`` to check.
        :return: ``True`` if the domain matches at least one record.
        """
        self.ensure_one()
        result = self._check_user_activity_batch(user, check_date)
        return user.id in result

    def _check_user_activity_batch(
        self, users: models.Model, check_date: date
    ) -> set[int]:
        """Check activity for multiple users at once, returning active user IDs.

        :param users: ``res.users`` recordset to check.
        :param check_date: ``date`` to check.
        :return: set of user IDs that had qualifying activity.
        """
        self.ensure_one()
        if not users:
            return set()

        # "Did you show up on day D?" is a calendar-day question, so the window
        # is built in the *user's* timezone and only then converted to UTC for
        # the query.  Storage stays UTC throughout — this mirrors
        # ``lunch.supplier._compute_available_today`` and
        # ``hr.employee._get_tz``, which resolve the relevant record's tz in
        # backend/cron code for exactly this reason.
        #
        # Note ``fields.Date.context_today`` is deliberately *not* used: it
        # reads ``env.tz``, which in a cron is the cron user's timezone, not
        # the streak owner's.
        active_ids: set[int] = set()
        users_by_tz: dict[str, list[int]] = {}
        for user in users:
            users_by_tz.setdefault(self._get_streak_tz_name(user), []).append(user.id)
        for tz_name, user_ids in users_by_tz.items():
            active_ids |= self._check_user_activity_window(
                users.browse(user_ids), check_date, tz_name
            )
        return active_ids

    def _get_streak_tz_name(self, user) -> str:
        """Return the timezone whose calendar day defines this user's streak.

        Falls back the same way ``hr.employee._get_tz`` does, ending in UTC so
        the behaviour is unchanged for users with no timezone set.
        """
        return user.tz or user.company_id.partner_id.tz or "UTC"

    def _get_day_bounds_utc(self, check_date: date, tz_name: str) -> tuple[str, str]:
        """Return the naive-UTC ``[start, end]`` strings bounding ``check_date``
        as that day is experienced in ``tz_name``.
        """
        tz = pytz.timezone(tz_name)
        start_local = tz.localize(datetime.combine(check_date, time.min))
        end_local = tz.localize(datetime.combine(check_date, time.max))
        return (
            fields.Datetime.to_string(
                start_local.astimezone(pytz.utc).replace(tzinfo=None)
            ),
            fields.Datetime.to_string(
                end_local.astimezone(pytz.utc).replace(tzinfo=None)
            ),
        )

    def _check_user_activity_window(
        self, users: models.Model, check_date: date, tz_name: str
    ) -> set[int]:
        """Check activity for users sharing one timezone.

        :param users: ``res.users`` recordset, all resolving to ``tz_name``.
        :param check_date: calendar day to check, in ``tz_name``.
        :param tz_name: IANA timezone name.
        :return: set of user IDs that had qualifying activity.
        """
        self.ensure_one()
        Obj = self.env[self.model_id.model].sudo()
        date_from, date_to = self._get_day_bounds_utc(check_date, tz_name)
        # Build a domain that works for all users in the batch.
        # The safe_eval domain may reference 'user' — we evaluate once
        # with a dummy user to get the base domain, then widen it.
        # If the domain actually uses 'user', fall back to per-user.
        first_user = users[0]
        domain = safe_eval(
            self.domain,
            {"user": first_user, "date_from": date_from, "date_to": date_to},
        )
        date_field = self.date_field_id.name
        domain += [
            (date_field, ">=", date_from),
            (date_field, "<=", date_to),
        ]

        # Check if domain contains a user-specific filter by evaluating
        # with a second user (if available) and comparing.
        domain_is_user_specific = False
        if len(users) > 1:
            second_domain = safe_eval(
                self.domain,
                {"user": users[1], "date_from": date_from, "date_to": date_to},
            )
            domain_is_user_specific = domain != second_domain

        if domain_is_user_specific:
            # Fall back to per-user evaluation when domain references user
            active_ids: set[int] = set()
            for user in users:
                user_domain = safe_eval(
                    self.domain,
                    {"user": user, "date_from": date_from, "date_to": date_to},
                )
                user_domain += [
                    (date_field, ">=", date_from),
                    (date_field, "<=", date_to),
                ]
                if Obj.search_count(user_domain, limit=1) > 0:
                    active_ids.add(user.id)
            return active_ids

        # Domain does not reference user — a single query checks if any
        # record matches.  This means ALL users get credit when the domain
        # matches, which is correct: a non-user-specific streak (e.g.,
        # "any sale happened") is a team/global streak by definition.
        if Obj.search_count(domain, limit=1) > 0:
            return set(users.ids)
        return set()


class GamificationStreak(models.Model):
    """Per-user streak instance tracking consecutive daily activity."""

    _name = "gamification.streak"
    _description = "User Activity Streak"
    _order = "current_count desc, id"
    _rec_name = "streak_type_id"

    user_id = fields.Many2one(
        "res.users",
        string="User",
        required=True,
        index=True,
        ondelete="cascade",
        default=lambda self: self.env.uid,
    )
    streak_type_id = fields.Many2one(
        "gamification.streak.type",
        string="Streak Type",
        required=True,
        index=True,
        ondelete="cascade",
    )
    current_count = fields.Integer("Current Streak", default=0, readonly=True)
    longest_count = fields.Integer("Longest Streak", default=0, readonly=True)
    last_activity_date = fields.Date("Last Activity", readonly=True)
    last_checked_date = fields.Date(
        "Last Checked",
        readonly=True,
        index=True,
        help="Day the streak cron last evaluated this streak, whatever the "
        "outcome. Used to make the cron idempotent.",
    )
    freeze_remaining = fields.Integer(
        "Freeze Days Left",
        default=0,
        help="Days remaining this month where the streak won't break.",
    )
    state = fields.Selection(
        [("active", "Active"), ("broken", "Broken")],
        default="active",
        required=True,
        readonly=True,
        index=True,
    )
    total_karma_earned = fields.Integer("Total Karma Earned", default=0, readonly=True)

    _user_streak_type_uniq = models.UniqueIndex(
        "(user_id, streak_type_id)",
        "A user can only have one streak per type.",
    )

    @api.depends("streak_type_id", "current_count")
    def _compute_display_name(self) -> None:
        """Display as 'Streak Name — 42 days'."""
        for rec in self:
            rec.display_name = f"{rec.streak_type_id.name} — {rec.current_count} days"

    def _record_activity(self) -> None:
        """Record that the user performed the streak activity today.

        Called by the daily cron or can be triggered manually.
        Increments the streak, grants karma bonuses at milestones.
        """
        today = fields.Date.today()
        for streak in self:
            if streak.last_activity_date == today:
                continue  # already recorded today
            streak.current_count += 1
            streak.last_activity_date = today
            streak.longest_count = max(streak.longest_count, streak.current_count)
            if streak.state == "broken":
                streak.state = "active"

            # Grant karma bonus
            karma = streak.streak_type_id.karma_bonus
            if karma:
                multiplier = STREAK_MILESTONES.get(streak.current_count, 1)
                total = karma * multiplier
                streak.user_id.sudo()._add_karma(
                    total,
                    source=streak,
                    reason=_(
                        "Streak day %(day)s: %(streak)s",
                        day=streak.current_count,
                        streak=streak.streak_type_id.name,
                    ),
                )
                streak.total_karma_earned += total

                # Bus notification + activity feed on milestone days
                if streak.current_count in STREAK_MILESTONES:
                    streak.user_id._send_gamification_notification(
                        "streak",
                        {
                            "title": _("Streak Milestone!"),
                            "message": _(
                                "%(streak)s — %(days)s days!",
                                streak=streak.streak_type_id.name,
                                days=streak.current_count,
                            ),
                        },
                    )
                    self.env["gamification.activity"]._log_streak_milestone(
                        streak.user_id,
                        streak.streak_type_id,
                        streak.current_count,
                        total,
                    )

    def _break_streak(self) -> None:
        """Break the streak — reset current count but preserve longest."""
        self.write(
            {
                "state": "broken",
                "current_count": 0,
            }
        )

    @api.model
    def _cron_update_streaks(self) -> None:
        """Daily cron: check all active streaks and break those without activity.

        For each active streak, checks if the user had qualifying activity
        yesterday.  If not, uses a freeze day or breaks the streak.
        Also resets freeze allowance on the 1st of each month.
        """
        today = fields.Date.today()
        yesterday = today - timedelta(days=1)

        # Reset freeze allowance on 1st of month — batch by type
        if today.day == 1:
            active_streaks = self.search([("state", "=", "active")])
            # Group by streak type for batch writes
            by_type: dict[int, list[int]] = {}
            for streak in active_streaks:
                by_type.setdefault(streak.streak_type_id.id, []).append(streak.id)
            for type_id, streak_ids in by_type.items():
                stype = self.env["gamification.streak.type"].browse(type_id)
                self.browse(streak_ids).write(
                    {"freeze_remaining": stype.freeze_allowance}
                )

        # Check active and broken streaks — broken ones can revive if the
        # user performed qualifying activity yesterday.
        #
        # The re-entry guard is ``last_checked_date``, not
        # ``last_activity_date``: the latter only advances when activity is
        # *found*, so the freeze and break branches were not idempotent.  A
        # second run on the same day (an admin using "Run Manually", or a cron
        # retry) burned another freeze day, and a third broke a streak the user
        # had never actually missed.
        active_streaks = self.search(
            [
                ("state", "in", ["active", "broken"]),
                "|",
                ("last_checked_date", "<", today),
                ("last_checked_date", "=", False),
            ]
        )
        for streak in active_streaks:
            # One bad streak type must not abort the whole run: a malformed or
            # stale domain raises inside safe_eval/search, which would roll
            # back every streak already processed and leave the same poison
            # record blocking the next run too.
            try:
                with self.env.cr.savepoint():
                    self._process_streak_day(streak, yesterday)
            except Exception:
                _logger.exception(
                    "Streak check failed for streak %s (type %s, user %s); "
                    "skipping it and continuing the run.",
                    streak.id,
                    streak.streak_type_id.name,
                    streak.user_id.login,
                )

    def _process_streak_day(self, streak, check_date) -> None:
        """Evaluate a single streak for ``check_date`` and record the outcome."""
        had_activity = streak.streak_type_id._check_user_activity(
            streak.user_id,
            check_date,
        )
        if had_activity:
            streak._record_activity()
        elif streak.state == "broken":
            # Already broken — nothing to freeze or break further
            pass
        elif streak.freeze_remaining > 0:
            streak.freeze_remaining -= 1
            _logger.info(
                "Streak freeze used: %s for user %s (%s remaining)",
                streak.streak_type_id.name,
                streak.user_id.login,
                streak.freeze_remaining,
            )
        else:
            _logger.info(
                "Streak broken: %s for user %s (was %s days)",
                streak.streak_type_id.name,
                streak.user_id.login,
                streak.current_count,
            )
            streak._break_streak()

        # Mark the day as evaluated whatever the outcome, so a repeat run in
        # the same day is a no-op.
        streak.last_checked_date = fields.Date.today()

    @api.model
    def _ensure_user_streaks(self, user: models.Model | None = None) -> None:
        """Ensure a streak record exists for every active streak type.

        Called when a user first accesses gamification features.
        Creates missing streak records with default values.
        Uses a single SQL query to find missing types.
        """
        user = user or self.env.user
        self.env.cr.execute(
            """
            SELECT st.id, st.freeze_allowance
            FROM gamification_streak_type st
            WHERE st.active IS TRUE
              AND NOT EXISTS (
                  SELECT 1 FROM gamification_streak gs
                  WHERE gs.streak_type_id = st.id AND gs.user_id = %s
              )
            """,
            [user.id],
        )
        missing = self.env.cr.fetchall()
        if missing:
            self.sudo().create(
                [
                    {
                        "user_id": user.id,
                        "streak_type_id": type_id,
                        "freeze_remaining": freeze_allowance,
                    }
                    for type_id, freeze_allowance in missing
                ]
            )

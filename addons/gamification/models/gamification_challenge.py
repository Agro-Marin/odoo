import ast
import itertools
import logging
from datetime import date, timedelta
from typing import Any, Literal, Self

from dateutil.relativedelta import relativedelta
from markupsafe import Markup

from odoo import Command, _, api, exceptions, fields, models
from odoo.http import SESSION_LIFETIME
from odoo.models import ValuesType
from odoo.tools import SQL

from .gamification_utils import start_end_date_for_period

_logger = logging.getLogger(__name__)

MAX_VISIBILITY_RANKING = 3


class GamificationChallenge(models.Model):
    """Set of predefined objectives assigned to people with recurrence rules and rewards.

    If *user_ids* is populated and *period* is not ``'once'``, goals are
    regenerated for each period (e.g. every 1st of the month for ``'monthly'``).
    """

    _name = "gamification.challenge"
    _description = "Gamification Challenge"
    _inherit = ["mail.thread"]
    _order = "end_date, start_date, name, id"

    @api.model
    def default_get(self, fields: list[str]) -> dict[str, Any]:
        res = super().default_get(fields)
        if "user_domain" in fields and "user_domain" not in res:
            user_group_id = self.env.ref("base.group_user")
            res["user_domain"] = (
                f'["&", ("all_group_ids", "in", [{user_group_id.id}]), ("active", "=", True)]'
            )
        return res

    # description
    name = fields.Char("Challenge Name", required=True, translate=True)
    description = fields.Text("Description", translate=True)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("inprogress", "In Progress"),
            ("done", "Done"),
        ],
        default="draft",
        copy=False,
        string="State",
        required=True,
        tracking=True,
    )
    manager_id = fields.Many2one(
        "res.users", default=lambda self: self.env.uid, string="Responsible"
    )
    # members
    user_ids = fields.Many2many(
        "res.users", "gamification_challenge_users_rel", string="Participants"
    )
    user_domain = fields.Char("User domain")  # Alternative to a list of users
    user_count = fields.Integer("# Users", compute="_compute_user_count")
    # periodicity
    period = fields.Selection(
        [
            ("once", "Non recurring"),
            ("daily", "Daily"),
            ("weekly", "Weekly"),
            ("monthly", "Monthly"),
            ("yearly", "Yearly"),
        ],
        default="once",
        string="Periodicity",
        help="Period of automatic goal assignment. If none is selected, should be launched manually.",
        required=True,
    )
    start_date = fields.Date(
        "Start Date",
        help="The day a new challenge will be automatically started. If no periodicity is set, will use this date as the goal start date.",
    )
    end_date = fields.Date(
        "End Date",
        help="The day a new challenge will be automatically closed. If no periodicity is set, will use this date as the goal end date.",
    )

    invited_user_ids = fields.Many2many(
        "res.users", "gamification_invited_user_ids_rel", string="Suggest to users"
    )

    line_ids = fields.One2many(
        "gamification.challenge.line",
        "challenge_id",
        string="Lines",
        help="List of goals that will be set",
        required=True,
        copy=True,
    )

    reward_id = fields.Many2one(
        "gamification.badge", string="For Every Succeeding User", index="btree_not_null"
    )
    reward_first_id = fields.Many2one("gamification.badge", string="For 1st user")
    reward_second_id = fields.Many2one("gamification.badge", string="For 2nd user")
    reward_third_id = fields.Many2one("gamification.badge", string="For 3rd user")
    reward_failure = fields.Boolean("Reward Bests if not Succeeded?")
    reward_realtime = fields.Boolean(
        "Reward as soon as every goal is reached",
        default=True,
        help="With this option enabled, a user can receive a badge only once. The top 3 badges are still rewarded only at the end of the challenge.",
    )

    visibility_mode = fields.Selection(
        [
            ("personal", "Individual Goals"),
            ("ranking", "Leader Board (Group Ranking)"),
        ],
        default="personal",
        string="Display Mode",
        required=True,
    )

    # Team mode
    challenge_mode = fields.Selection(
        [
            ("individual", "Individual"),
            ("team", "Team vs Team"),
        ],
        default="individual",
        required=True,
        string="Competition Mode",
    )
    team_ids = fields.Many2many(
        "gamification.team",
        "gamification_challenge_team_rel",
        string="Competing Teams",
        help="Teams participating in this challenge. Each team's score is "
        "the average completeness of its members' goals.",
    )

    report_message_frequency = fields.Selection(
        [
            ("never", "Never"),
            ("onchange", "On change"),
            ("daily", "Daily"),
            ("weekly", "Weekly"),
            ("monthly", "Monthly"),
            ("yearly", "Yearly"),
        ],
        default="never",
        string="Report Frequency",
        required=True,
    )
    report_message_group_id = fields.Many2one(
        "discuss.channel",
        string="Send a copy to",
        help="Group that will receive a copy of the report in addition to the user",
    )
    report_template_id = fields.Many2one(
        "mail.template",
        default=lambda self: self._get_report_template(),
        string="Report Template",
        required=True,
    )
    remind_update_delay = fields.Integer(
        "Non-updated manual goals will be reminded after",
        help="Never reminded if no value or zero is specified.",
    )
    last_report_date = fields.Date("Last Report Date", default=fields.Date.today)
    next_report_date = fields.Date(
        "Next Report Date", compute="_get_next_report_date", store=True
    )

    season_id = fields.Many2one(
        "gamification.season",
        string="Season",
        index="btree_not_null",
        ondelete="set null",
        help="Season this challenge belongs to. Leave empty for permanent challenges.",
    )

    challenge_category = fields.Selection(
        [
            ("hr", "Human Resources / Engagement"),
            ("other", "Settings / Gamification Tools"),
        ],
        string="Appears in",
        required=True,
        default="hr",
        help="Define the visibility of the challenge through menus",
    )

    @api.depends("user_ids", "user_ids.active")
    def _compute_user_count(self) -> None:
        mapped_data = {}
        if self.ids:
            query = """
                SELECT gamification_challenge_id, count(users.id)
                  FROM gamification_challenge_users_rel rel
             LEFT JOIN res_users users
                    ON users.id=rel.res_users_id AND users.active = TRUE
                 WHERE gamification_challenge_id = ANY(%s)
              GROUP BY gamification_challenge_id
            """
            self.env.cr.execute(query, [list(self.ids)])
            mapped_data = dict(self.env.cr.fetchall())
        for challenge in self:
            challenge.user_count = mapped_data.get(challenge.id, 0)

    REPORT_OFFSETS = {
        "daily": timedelta(days=1),
        "weekly": timedelta(days=7),
        "monthly": relativedelta(months=1),
        "yearly": relativedelta(years=1),
    }

    @api.depends("last_report_date", "report_message_frequency")
    def _get_next_report_date(self) -> None:
        """Return the next report date based on the last report date and
        report period.
        """
        for challenge in self:
            last = challenge.last_report_date
            offset = self.REPORT_OFFSETS.get(challenge.report_message_frequency)

            if offset:
                challenge.next_report_date = last + offset
            else:
                challenge.next_report_date = False

    def _get_report_template(self) -> int | Literal[False]:
        template = self.env.ref(
            "gamification.simple_report_template", raise_if_not_found=False
        )

        return template.id if template else False

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        """Overwrite the create method to add the user of groups"""
        for vals in vals_list:
            if user_domain := vals.get("user_domain"):
                users = self._get_challenger_users(str(user_domain))

                if not vals.get("user_ids"):
                    vals["user_ids"] = []
                vals["user_ids"].extend(Command.link(user.id) for user in users)

        return super().create(vals_list)

    def write(self, vals: ValuesType) -> Literal[True]:
        # Validate BEFORE mutation: resetting to draft with unfinished goals is forbidden
        if vals.get("state") == "draft":
            if self.env["gamification.goal"].search_count(
                [
                    ("challenge_id", "in", self.ids),
                    ("state", "=", "inprogress"),
                ],
                limit=1,
            ):
                raise exceptions.UserError(
                    _("You can not reset a challenge with unfinished goals.")
                )

        if user_domain := vals.get("user_domain"):
            users = self._get_challenger_users(str(user_domain))

            if not vals.get("user_ids"):
                vals["user_ids"] = []
            vals["user_ids"].extend(Command.link(user.id) for user in users)

        write_res = super().write(vals)

        if vals.get("state") == "inprogress":
            self._recompute_challenge_users()
            self._generate_goals_from_challenge()

        elif vals.get("state") == "done":
            self._check_challenge_reward(force=True)

        return write_res

    @api.model
    def _cron_update(self, ids: list[int] | bool = False, commit: bool = True) -> bool:
        """Daily cron: start/close scheduled challenges and update goals.

        Called by ``ir.cron``.  Sets ``commit_gamification`` context so that
        side-effect writes (goal creation, badge grants) are committed
        incrementally rather than in one huge transaction.
        """
        # in cron mode, will do intermediate commits
        # cannot be replaced by a parameter because it is intended to impact side-effects of
        # write operations
        self = self.with_context(commit_gamification=commit)
        # start scheduled challenges
        planned_challenges = self.search(
            [("state", "=", "draft"), ("start_date", "<=", fields.Date.today())]
        )
        if planned_challenges:
            planned_challenges.write({"state": "inprogress"})

        # close scheduled challenges
        scheduled_challenges = self.search(
            [("state", "=", "inprogress"), ("end_date", "<", fields.Date.today())]
        )
        if scheduled_challenges:
            scheduled_challenges.write({"state": "done"})

        records = (
            self.browse(ids) if ids else self.search([("state", "=", "inprogress")])
        )

        return records._update_all()

    def _update_all(self) -> bool:
        """Update the challenges and related goals."""
        if not self:
            return True

        Goals = self.env["gamification.goal"]
        self.flush_recordset()
        self.user_ids.presence_ids.flush_recordset()
        # include yesterday goals to update the goals that just ended
        # exclude goals for users that have not interacted with the
        # webclient since the last update or whose session is no longer
        # valid.
        yesterday = fields.Date.to_string(date.today() - timedelta(days=1))
        self.env.cr.execute(
            """SELECT gg.id
                        FROM gamification_goal as gg
                        JOIN mail_presence as mp ON mp.user_id = gg.user_id
                       WHERE gg.write_date <= mp.last_presence
                         AND mp.last_presence >= now() AT TIME ZONE 'UTC' - interval '%(session_lifetime)s seconds'
                         AND gg.closed IS NOT TRUE
                         AND gg.challenge_id = ANY(%(challenge_ids)s)
                         AND (gg.state = 'inprogress'
                              OR (gg.state = 'reached' AND gg.end_date >= %(yesterday)s))
                      GROUP BY gg.id
        """,
            {
                "session_lifetime": SESSION_LIFETIME,
                "challenge_ids": list(self.ids),
                "yesterday": yesterday,
            },
        )

        Goals.browse(goal_id for [goal_id] in self.env.cr.fetchall()).update_goal()

        self._recompute_challenge_users()
        self._generate_goals_from_challenge()

        for challenge in self:
            if challenge.last_report_date != fields.Date.today():
                if (
                    challenge.next_report_date
                    and fields.Date.today() >= challenge.next_report_date
                ):
                    challenge.report_progress()
                else:
                    # goals closed but still opened at the last report date
                    closed_goals_to_report = Goals.search(
                        [
                            ("challenge_id", "=", challenge.id),
                            ("start_date", "<=", challenge.last_report_date),
                            ("end_date", ">=", challenge.last_report_date),
                        ]
                    )
                    if closed_goals_to_report:
                        # some goals need a final report
                        challenge.report_progress(subset_goals=closed_goals_to_report)

        self._check_challenge_reward()
        return True

    def _get_challenger_users(self, domain: str) -> models.Model:
        user_domain = ast.literal_eval(domain)
        return self.env["res.users"].search(user_domain)

    def _recompute_challenge_users(self) -> bool:
        """Recompute participants from domain and team memberships.

        Domain users are **added** to existing participants (not replaced),
        so manually-added users are preserved.
        """
        for challenge in self:
            new_users = challenge.user_ids

            # Union domain users into existing participants
            if challenge.user_domain:
                new_users |= self._get_challenger_users(challenge.user_domain)

            # Add all team members for team challenges
            if challenge.challenge_mode == "team" and challenge.team_ids:
                new_users |= challenge.team_ids.mapped("member_ids")

            if challenge.user_ids != new_users:
                challenge.user_ids = new_users

        return True

    def action_start(self) -> bool:
        """Start a challenge"""
        return self.write({"state": "inprogress"})

    def action_check(self) -> bool:
        """Refresh challenge goals.

        Recreates automatic in-progress goals to reflect structural changes
        (added/removed lines or participants).  Manual goals are preserved
        to avoid losing user-entered progress.
        """
        self.env["gamification.goal"].search(
            [
                ("challenge_id", "in", self.ids),
                ("state", "=", "inprogress"),
                ("definition_id.computation_mode", "!=", "manually"),
            ]
        ).unlink()

        return self._update_all()

    def action_report_progress(self) -> bool:
        """Manual report of a goal, does not influence automatic report frequency"""
        for challenge in self:
            challenge.report_progress()
        return True

    def action_view_users(self) -> dict[str, Any]:
        """Redirect to the participants (users) list."""
        action = self.env["ir.actions.actions"]._for_xml_id("base.action_res_users")
        action["domain"] = [("id", "in", self.user_ids.ids)]
        return action

    # --- Automatic actions ---

    def _generate_goals_from_challenge(self) -> bool:
        """Generate goals for each challenge line and participant.

        Skips lines where a goal already exists for a given user and period.
        Called after any change to the participant list or goal lines.
        """
        Goals = self.env["gamification.goal"]
        for challenge in self:
            (start_date, end_date) = start_end_date_for_period(
                challenge.period, challenge.start_date, challenge.end_date
            )
            to_update = Goals.browse(())
            adaptive_targets = challenge._compute_adaptive_targets()

            for line in challenge.line_ids:
                # there is potentially a lot of users
                # detect the ones with no goal linked to this line
                date_clause = SQL()
                if start_date:
                    date_clause = SQL("%s AND start_date = %s", date_clause, start_date)
                if end_date:
                    date_clause = SQL("%s AND end_date = %s", date_clause, end_date)

                self.env.cr.execute(
                    SQL(
                        """SELECT DISTINCT user_id
                         FROM gamification_goal
                        WHERE line_id = %s
                              %s""",
                        line.id,
                        date_clause,
                    )
                )
                user_with_goal_ids = {it for [it] in self.env.cr.fetchall()}

                participant_user_ids = set(challenge.user_ids.ids)
                user_squating_challenge_ids = user_with_goal_ids - participant_user_ids
                if user_squating_challenge_ids:
                    # Users that used to match the challenge: drop only their
                    # goal for THIS line and period.  Scoping to line + period
                    # preserves their goals on other lines and their closed
                    # historical goals (which adaptive difficulty reads back).
                    squat_domain = [
                        ("line_id", "=", line.id),
                        ("user_id", "in", list(user_squating_challenge_ids)),
                    ]
                    if start_date:
                        squat_domain.append(("start_date", "=", start_date))
                    if end_date:
                        squat_domain.append(("end_date", "=", end_date))
                    Goals.search(squat_domain).unlink()

                values = {
                    "definition_id": line.definition_id.id,
                    "line_id": line.id,
                    "target_goal": line.target_goal,
                    "state": "inprogress",
                }

                if start_date:
                    values["start_date"] = start_date
                if end_date:
                    values["end_date"] = end_date

                # the goal is initialised over the limit to make sure we will compute it at least once
                if line.condition == "higher":
                    values["current"] = min(line.target_goal - 1, 0)
                else:
                    values["current"] = max(line.target_goal + 1, 0)

                if challenge.remind_update_delay:
                    values["remind_update_delay"] = challenge.remind_update_delay

                new_user_ids = participant_user_ids - user_with_goal_ids
                if new_user_ids:
                    goal_vals = []
                    for uid in new_user_ids:
                        user_target = adaptive_targets.get(
                            (uid, line.id), values["target_goal"]
                        )
                        user_vals = {
                            **values,
                            "user_id": uid,
                            "target_goal": user_target,
                        }
                        # Recompute initial "current" for the adjusted target
                        if line.condition == "higher":
                            user_vals["current"] = min(user_target - 1, 0)
                        else:
                            user_vals["current"] = max(user_target + 1, 0)
                        goal_vals.append(user_vals)
                    to_update |= Goals.create(goal_vals)

            to_update.update_goal()

            if self.env.context.get("commit_gamification"):
                self.env.cr.commit()

        return True

    # --- Serialization ---

    def _get_serialized_challenge_lines(
        self, user=(), restrict_goals=(), restrict_top: int = 0
    ) -> list[dict[str, Any]]:
        """Return serialized goal data only when the user has completed every goal.

        For personal visibility, returns an empty list if any goal is not
        yet reached (used to trigger completion reports, not progress reports).

        :param user: user retrieving progress (False if no distinction,
                     only for ranking challenges)
        :param restrict_goals: compute only the results for this subset of
                               gamification.goal ids, if False retrieve every
                               goal of current running challenge
        :param int restrict_top: for challenge lines where visibility_mode is
                                 ``ranking``, retrieve only the best
                                 ``restrict_top`` results and itself, if 0
                                 retrieve all restrict_goal_ids has priority
                                 over restrict_top

        format list
        # if visibility_mode == 'ranking'
        {
            'name': <gamification.goal.description name>,
            'description': <gamification.goal.description description>,
            'condition': <reach condition {lower,higher}>,
            'computation_mode': <target computation {manually,count,sum,python}>,
            'monetary': <{True,False}>,
            'suffix': <value suffix>,
            'action': <{True,False}>,
            'display_mode': <{progress,boolean}>,
            'target': <challenge line target>,
            'own_goal_id': <gamification.goal id where user_id == uid>,
            'goals': [
                {
                    'id': <gamification.goal id>,
                    'rank': <user ranking>,
                    'user_id': <res.users id>,
                    'name': <res.users name>,
                    'state': <gamification.goal state {draft,inprogress,reached,failed,canceled}>,
                    'completeness': <percentage>,
                    'current': <current value>,
                }
            ]
        },
        # if visibility_mode == 'personal'
        {
            'id': <gamification.goal id>,
            'name': <gamification.goal.description name>,
            'description': <gamification.goal.description description>,
            'condition': <reach condition {lower,higher}>,
            'computation_mode': <target computation {manually,count,sum,python}>,
            'monetary': <{True,False}>,
            'suffix': <value suffix>,
            'action': <{True,False}>,
            'display_mode': <{progress,boolean}>,
            'target': <challenge line target>,
            'state': <gamification.goal state {draft,inprogress,reached,failed,canceled}>,
            'completeness': <percentage>,
            'current': <current value>,
        }
        """
        Goals = self.env["gamification.goal"]
        (start_date, end_date) = start_end_date_for_period(self.period)

        # Prefetch all goals for all lines in a single query
        base_domain = [
            ("line_id", "in", self.line_ids.ids),
            ("state", "!=", "draft"),
        ]
        if restrict_goals:
            base_domain.append(("id", "in", restrict_goals.ids))
        else:
            if start_date:
                base_domain.append(("start_date", "=", start_date))
            if end_date:
                base_domain.append(("end_date", "=", end_date))
        if self.visibility_mode == "personal":
            if not user:
                raise exceptions.UserError(
                    _(
                        "Retrieving progress for personal challenge without user information"
                    )
                )
            base_domain.append(("user_id", "=", user.id))

        all_goals = Goals.search_fetch(
            base_domain,
            [
                "line_id",
                "user_id",
                "current",
                "completeness",
                "state",
                "definition_condition",
            ],
        )
        # Partition goals by line_id
        goals_by_line: dict = {}
        for goal in all_goals:
            goals_by_line.setdefault(goal.line_id.id, Goals.browse(()))
            goals_by_line[goal.line_id.id] |= goal

        res_lines = []
        for line in self.line_ids:
            line_data = {
                "name": line.definition_id.name,
                "description": line.definition_id.description,
                "condition": line.definition_id.condition,
                "computation_mode": line.definition_id.computation_mode,
                "monetary": line.definition_id.monetary,
                "suffix": line.definition_id.suffix,
                "full_suffix": line.definition_id.full_suffix,
                "action": bool(line.definition_id.action_id),
                "display_mode": line.definition_id.display_mode,
                "target": line.target_goal,
            }
            goals = goals_by_line.get(line.id, Goals.browse(()))

            if self.visibility_mode == "personal":
                goal = goals[:1]
                if not goal:
                    continue
                if goal.state != "reached":
                    return []
                line_data.update(
                    {
                        fname: goal[fname]
                        for fname in ["id", "current", "completeness", "state"]
                    }
                )
                res_lines.append(line_data)
                continue

            line_data["own_goal_id"] = False
            line_data["goals"] = []
            if not goals:
                continue
            goals = goals.sorted(
                key=lambda g: (
                    -g.completeness,
                    -g.current if line.condition == "higher" else g.current,
                )
            )

            for ranking, goal in enumerate(goals):
                if user and goal.user_id == user:
                    line_data["own_goal_id"] = goal.id
                elif restrict_top and ranking >= restrict_top:
                    continue

                line_data["goals"].append(
                    {
                        "id": goal.id,
                        "user_id": goal.user_id.id,
                        "name": goal.user_id.name,
                        "rank": ranking,
                        "current": goal.current,
                        "completeness": goal.completeness,
                        "state": goal.state,
                    }
                )
            # Pad to at least 3 entries for display
            for ranking in range(len(goals), 3):
                line_data["goals"].append(
                    {
                        "id": False,
                        "user_id": False,
                        "name": "",
                        "current": 0,
                        "completeness": 0,
                        "state": False,
                        "rank": ranking,
                    }
                )

            res_lines.append(line_data)
        return res_lines

    # --- Reporting ---

    def report_progress(self, users=(), subset_goals=False) -> bool:
        """Post report about the progress of the goals

        :param users: users that are concerned by the report. If False, will
                      send the report to every user concerned (goal users and
                      group that receive a copy). Only used for challenge with
                      a visibility mode set to 'personal'.
        :param subset_goals: goals to restrict the report
        """
        challenge = self

        if challenge.visibility_mode == "ranking":
            lines_boards = challenge._get_serialized_challenge_lines(
                restrict_goals=subset_goals
            )

            body_html = challenge.report_template_id.with_context(
                challenge_lines=lines_boards
            )._render_field("body_html", challenge.ids)[challenge.id]

            # send to every follower and participant of the challenge
            challenge.message_post(
                body=body_html,
                partner_ids=challenge.mapped("user_ids.partner_id.id"),
                subtype_xmlid="mail.mt_comment",
                email_layout_xmlid="mail.mail_notification_light",
            )
            if challenge.report_message_group_id:
                challenge.report_message_group_id.message_post(
                    body=body_html, subtype_xmlid="mail.mt_comment"
                )

        else:
            # generate individual reports
            for user in users or challenge.user_ids:
                lines = challenge._get_serialized_challenge_lines(
                    user, restrict_goals=subset_goals
                )
                if not lines:
                    continue
                body_html = (
                    challenge.report_template_id.with_user(user)
                    .with_context(challenge_lines=lines)
                    ._render_field("body_html", challenge.ids)[challenge.id]
                )

                # notify message only to users, do not post on the challenge
                challenge.message_notify(
                    body=body_html,
                    partner_ids=[user.partner_id.id],
                    subtype_xmlid="mail.mt_comment",
                    email_layout_xmlid="mail.mail_notification_light",
                )
                if challenge.report_message_group_id:
                    challenge.report_message_group_id.message_post(
                        body=body_html,
                        subtype_xmlid="mail.mt_comment",
                        email_layout_xmlid="mail.mail_notification_light",
                    )
        return challenge.write({"last_report_date": fields.Date.today()})

    # --- Challenge participation ---
    def accept_challenge(self) -> bool:
        user = self.env.user
        sudoed = self.sudo()
        sudoed.message_post(body=_("%s has joined the challenge", user.name))
        sudoed.write(
            {
                "invited_user_ids": [Command.unlink(user.id)],
                "user_ids": [Command.link(user.id)],
            }
        )
        return sudoed._generate_goals_from_challenge()

    def discard_challenge(self) -> bool:
        """The user discard the suggested challenge"""
        user = self.env.user
        sudoed = self.sudo()
        sudoed.message_post(body=_("%s has refused the challenge", user.name))
        return sudoed.write({"invited_user_ids": [Command.unlink(user.id)]})

    def _check_challenge_reward(self, force: bool = False) -> bool:
        """Actions for the end of a challenge

        If a reward was selected, grant it to the correct users.
        Rewards granted at:
            - the end date for a challenge with no periodicity
            - the end of a period for challenge with periodicity
            - when a challenge is manually closed
        (if no end date, a running challenge is never rewarded)
        """
        commit = self.env.context.get("commit_gamification") and self.env.cr.commit

        for challenge in self:
            (_start_date, end_date) = start_end_date_for_period(
                challenge.period, challenge.start_date, challenge.end_date
            )
            yesterday = date.today() - timedelta(days=1)

            rewarded_users = self.env["res.users"]
            challenge_ended = force or (end_date and end_date <= yesterday)
            if challenge.reward_id and (challenge_ended or challenge.reward_realtime):
                # not using start_date as atemporal goals have a start date but no end_date
                reached_goals = self.env["gamification.goal"]._read_group(
                    [
                        ("challenge_id", "=", challenge.id),
                        ("end_date", "=", end_date),
                        ("state", "=", "reached"),
                    ],
                    groupby=["user_id"],
                    aggregates=["__count"],
                )
                for user, count in reached_goals:
                    if count == len(challenge.line_ids):
                        # the user has succeeded every assigned goal
                        if challenge.reward_realtime:
                            badges = self.env["gamification.badge.user"].search_count(
                                [
                                    ("challenge_id", "=", challenge.id),
                                    ("badge_id", "=", challenge.reward_id.id),
                                    ("user_id", "=", user.id),
                                ]
                            )
                            if badges > 0:
                                # already received the badge for this challenge
                                continue
                        challenge._reward_user(user, challenge.reward_id)
                        rewarded_users |= user
                        if commit:
                            commit()

            if challenge_ended:
                # open chatter message
                message_body = _("The challenge %s is finished.", challenge.name)

                if rewarded_users:
                    message_body += Markup("<br/>") + _(
                        "Reward (badge %(badge_name)s) for every succeeding user was sent to %(users)s.",
                        badge_name=challenge.reward_id.name,
                        users=", ".join(rewarded_users.mapped("display_name")),
                    )
                else:
                    message_body += Markup("<br/>") + _(
                        "Nobody has succeeded to reach every goal, no badge is rewarded for this challenge."
                    )

                # reward bests
                reward_message = Markup(
                    "<br/> %(rank)d. %(user_name)s - %(reward_name)s"
                )
                if challenge.reward_first_id:
                    (first_user, second_user, third_user) = challenge._get_topN_users(
                        MAX_VISIBILITY_RANKING
                    )
                    if first_user:
                        challenge._reward_user(first_user, challenge.reward_first_id)
                        message_body += Markup("<br/>") + _(
                            "Special rewards were sent to the top competing users. The ranking for this challenge is:"
                        )
                        message_body += reward_message % {
                            "rank": 1,
                            "user_name": first_user.name,
                            "reward_name": challenge.reward_first_id.name,
                        }
                    else:
                        message_body += _(
                            "Nobody reached the required conditions to receive special badges."
                        )

                    if second_user and challenge.reward_second_id:
                        challenge._reward_user(second_user, challenge.reward_second_id)
                        message_body += reward_message % {
                            "rank": 2,
                            "user_name": second_user.name,
                            "reward_name": challenge.reward_second_id.name,
                        }
                    if third_user and challenge.reward_third_id:
                        challenge._reward_user(third_user, challenge.reward_third_id)
                        message_body += reward_message % {
                            "rank": 3,
                            "user_name": third_user.name,
                            "reward_name": challenge.reward_third_id.name,
                        }

                challenge.message_post(
                    partner_ids=[user.partner_id.id for user in challenge.user_ids],
                    body=message_body,
                )
                if commit:
                    commit()

        return True

    def _get_topN_users(self, n: int) -> tuple[models.Model | Literal[False], ...]:
        """Get the top *n* users for this challenge, ranked by completeness.

        Ranking criteria (in order):
            1. Whether the user reached every goal of the challenge.
            2. Total completeness across all goals (can exceed 100 per goal
               for 'higher' conditions).

        Only users having reached every goal are returned unless
        ``reward_failure`` is set, in which case any participant may qualify.

        :param int n: number of ranked positions to return.
        :returns: tuple of exactly *n* elements — ``res.users`` records or
                  ``False`` for unfilled positions.  No ``False`` appears
                  between two users.
        """
        Goals = self.env["gamification.goal"]
        (start_date, end_date) = start_end_date_for_period(
            self.period, self.start_date, self.end_date
        )

        # Single query: fetch all goals for this challenge/period at once
        domain = [("challenge_id", "=", self.id)]
        if start_date:
            domain.append(("start_date", "=", start_date))
        if end_date:
            domain.append(("end_date", "=", end_date))
        all_goals = Goals.search_fetch(
            domain,
            ["user_id", "state", "definition_condition", "current", "target_goal"],
        )

        # Group goals by user and compute ranking metrics in Python
        goals_by_user: dict = {}
        for goal in all_goals:
            goals_by_user.setdefault(goal.user_id, []).append(goal)

        num_lines = len(self.line_ids)
        challengers = []
        for user in self.user_ids:
            user_goals = goals_by_user.get(user, [])
            all_reached = (
                all(g.state == "reached" for g in user_goals)
                and len(user_goals) == num_lines
            )
            total_completeness = 0.0
            for goal in user_goals:
                if goal.definition_condition == "higher":
                    total_completeness += (
                        min(100.0 * goal.current / goal.target_goal, 100.0)
                        if goal.target_goal
                        else 0
                    )
                elif goal.state == "reached":
                    total_completeness += 100
            challengers.append(
                {
                    "user": user,
                    "all_reached": all_reached,
                    "total_completeness": total_completeness,
                }
            )

        challengers.sort(
            key=lambda k: (k["all_reached"], k["total_completeness"]), reverse=True
        )
        if not self.reward_failure:
            challengers = itertools.takewhile(lambda c: c["all_reached"], challengers)

        # Pad with False to exactly n positions
        return tuple(
            itertools.islice(
                itertools.chain(
                    (c["user"] for c in challengers), itertools.repeat(False)
                ),
                n,
            )
        )

    def _get_team_rankings(self) -> list[dict[str, Any]]:
        """Rank teams by average member goal completeness for this challenge.

        :return: list of dicts ``[{'team': record, 'score': float}, ...]``
            sorted by score descending.
        """
        self.ensure_one()
        rankings = []
        for team in self.team_ids:
            score = team.get_team_challenge_score(self)
            rankings.append({"team": team, "score": score})
        rankings.sort(key=lambda r: r["score"], reverse=True)
        return rankings

    def _reward_user(self, user, badge) -> bool:
        """Grant a badge reward to a user for this challenge.

        Uses ``sudo()`` to bypass badge granting rules — the challenge
        system is a legitimate automated grant source (e.g. badges with
        ``rule_auth='nobody'`` are specifically designed for this).

        :param user: ``res.users`` record to reward.
        :param badge: ``gamification.badge`` record to grant.
        """
        return (
            self.env["gamification.badge.user"]
            .sudo()
            .create({"user_id": user.id, "badge_id": badge.id, "challenge_id": self.id})
            ._send_badge()
        )

    # ── Adaptive Difficulty ─────────────────────────────────────────

    def _compute_adaptive_targets(self):
        """Compute adjusted targets for recurring challenges based on performance.

        For each user in a recurring challenge, analyze their last 3 completed
        periods.  If they consistently exceed the target (>90% avg), increase
        by 15%.  If they consistently miss (<50% avg), decrease by 15%.

        :return: dict mapping ``{(user_id, line_id): adjusted_target}``.
        """
        self.ensure_one()
        if self.period == "once":
            return {}

        Goal = self.env["gamification.goal"]
        adjustments = {}

        # Batch: single search for all past closed goals in this challenge
        all_past_goals = Goal.search(
            [
                ("line_id", "in", self.line_ids.ids),
                ("user_id", "in", self.user_ids.ids),
                ("closed", "=", True),
                ("state", "in", ["reached", "failed"]),
            ],
            order="end_date desc",
        )
        # Group by (line_id, user_id) and keep at most 3 per pair
        goals_by_key: dict[tuple[int, int], list] = {}
        for g in all_past_goals:
            key = (g.line_id.id, g.user_id.id)
            bucket = goals_by_key.setdefault(key, [])
            if len(bucket) < 3:
                bucket.append(g)

        for line in self.line_ids:
            is_higher = line.condition == "higher"
            for user in self.user_ids:
                past_goals = goals_by_key.get((line.id, user.id), [])
                if len(past_goals) < 2:
                    continue  # Not enough history

                # Compute an average achievement ratio that is direction-aware:
                # >1 means the user comfortably beat the target, <1 means they
                # missed it — for both 'higher' (bigger is better) and 'lower'
                # (smaller is better) goals.
                rates = []
                for g in past_goals:
                    if not g.target_goal:
                        continue
                    if is_higher:
                        rates.append(min(g.current / g.target_goal, 2.0))
                    elif g.current:
                        rates.append(min(g.target_goal / g.current, 2.0))
                    else:
                        # perfect 'lower' result (0) — treat as strongly beating
                        rates.append(2.0)
                if not rates:
                    continue

                avg_rate = sum(rates) / len(rates)
                base_target = line.target_goal

                if avg_rate >= 1.0:
                    # Consistently *meeting or beating* the target — make it
                    # 15% harder.  Harder means a bigger target for 'higher', a
                    # smaller one for 'lower'.
                    #
                    # The threshold must not dip below 1.0: at > 0.9 a user
                    # averaging 91% of target — i.e. failing every single
                    # period — was handed a 15% harder target each round, so
                    # the people already struggling got the steepest ramp.
                    factor = 1.15 if is_higher else 0.85
                elif avg_rate < 0.5:
                    # Consistently missing — make it 15% easier.
                    factor = 0.85 if is_higher else 1.15
                else:
                    continue  # No adjustment needed

                adjusted = round(max(base_target * factor, 1), 2)
                adjustments[(user.id, line.id)] = adjusted

        return adjustments

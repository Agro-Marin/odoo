import ast
import logging
from datetime import date, datetime, timedelta
from typing import Any, Literal, Self

from odoo import _, api, exceptions, fields, models
from odoo.models import ValuesType
from odoo.tools.safe_eval import safe_eval, time

_logger = logging.getLogger(__name__)


class GamificationGoal(models.Model):
    """Individual goal instance for a user on a specific time period."""

    _name = "gamification.goal"
    _description = "Gamification Goal"
    _inherit = ["mail.thread"]
    _rec_name = "definition_id"
    _order = "start_date desc, end_date desc, definition_id, id"

    definition_id = fields.Many2one(
        "gamification.goal.definition",
        string="Goal Definition",
        required=True,
        ondelete="cascade",
    )
    user_id = fields.Many2one(
        "res.users",
        string="User",
        required=True,
        bypass_search_access=True,
        index=True,
        ondelete="cascade",
    )
    user_partner_id = fields.Many2one("res.partner", related="user_id.partner_id")
    line_id = fields.Many2one(
        "gamification.challenge.line", string="Challenge Line", ondelete="cascade"
    )
    challenge_id = fields.Many2one(
        related="line_id.challenge_id",
        store=True,
        readonly=True,
        index=True,
        help="Challenge that generated the goal, assign challenge to users "
        "to generate goals with a value in this field.",
    )
    start_date = fields.Date("Start Date", default=fields.Date.today)
    end_date = fields.Date("End Date")  # no start and end = always active
    target_goal = fields.Float("To Reach", required=True)
    # no goal = global index
    current = fields.Float("Current Value", required=True, default=0)
    completeness = fields.Float("Completeness", compute="_get_completion")
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("inprogress", "In progress"),
            ("reached", "Reached"),
            ("failed", "Failed"),
            ("canceled", "Cancelled"),
        ],
        default="draft",
        string="State",
        required=True,
        index=True,
    )
    to_update = fields.Boolean("To update")
    closed = fields.Boolean("Closed goal", index=True)

    computation_mode = fields.Selection(related="definition_id.computation_mode")
    color = fields.Integer("Color Index", compute="_compute_color")
    remind_update_delay = fields.Integer(
        "Remind delay",
        help="The number of days after which the user "
        "assigned to a manual goal will be reminded. "
        "Never reminded if no value is specified.",
    )
    last_update = fields.Date(
        "Last Update",
        help="In case of manual goal, reminders are sent if the goal as not "
        "been updated for a while (defined in challenge). Ignored in "
        "case of non-manual goal or goal not linked to a challenge.",
    )

    definition_description = fields.Text(
        "Definition Description", related="definition_id.description", readonly=True
    )
    definition_condition = fields.Selection(
        string="Definition Condition", related="definition_id.condition", readonly=True
    )
    definition_suffix = fields.Char(
        "Suffix", related="definition_id.full_suffix", readonly=True
    )
    definition_display = fields.Selection(
        string="Display Mode", related="definition_id.display_mode", readonly=True
    )

    @api.depends("end_date", "last_update", "state")
    def _compute_color(self) -> None:
        """Set the color based on the goal's state and completion"""
        for goal in self:
            goal.color = 0
            if goal.end_date and goal.last_update:
                if (goal.end_date < goal.last_update) and (goal.state == "failed"):
                    goal.color = 2
                elif (goal.end_date < goal.last_update) and (goal.state == "reached"):
                    goal.color = 5

    @api.depends("current", "target_goal", "definition_id.condition")
    def _get_completion(self) -> None:
        """Return the percentage of completeness of the goal, between 0 and 100"""
        for goal in self:
            if goal.definition_condition == "higher":
                if goal.current >= goal.target_goal:
                    goal.completeness = 100.0
                else:
                    goal.completeness = (
                        round(100.0 * goal.current / goal.target_goal, 2)
                        if goal.target_goal
                        else 0
                    )
            elif goal.current < goal.target_goal:
                # a goal 'lower than' has only two values possible: 0 or 100%
                goal.completeness = 100.0
            else:
                goal.completeness = 0.0

    def _check_remind_delay(self) -> dict[str, Any]:
        """Verify if a goal has not been updated for some time and send a
        reminder message of needed.

        :return: data to write on the goal object
        """
        self.ensure_one()
        if not (self.remind_update_delay and self.last_update):
            return {}

        delta_max = timedelta(days=self.remind_update_delay)
        if date.today() - self.last_update < delta_max:
            return {}

        # generate a reminder report
        body_html = self.env.ref(
            "gamification.email_template_goal_reminder"
        )._render_field("body_html", self.ids, compute_lang=True)[self.id]
        self.message_notify(
            body=body_html,
            partner_ids=[self.user_id.partner_id.id],
            subtype_xmlid="mail.mt_comment",
            email_layout_xmlid="mail.mail_notification_light",
        )

        return {"to_update": True}

    def _get_write_values(self, new_value: float) -> dict[Any, ValuesType]:
        """Generate values to write after recomputation of a goal score.

        State is evaluated from the goal's current situation, *not* from
        whether the measured value happened to move.  Skipping the whole method
        when ``new_value == self.current`` meant a goal whose metric was simply
        flat could never change state: an expired, unmet goal stayed
        ``inprogress`` and un-``closed`` for ever, was re-evaluated by the cron
        on every run, and permanently blocked resetting its challenge to draft.
        """
        result = {}
        if new_value != self.current:
            result["current"] = new_value

        # Draft goals have not started and cancelled ones were closed by hand;
        # neither should be moved by an automatic recomputation.
        if self.state not in ("inprogress", "reached"):
            return {self: result} if result else {}

        condition = self.definition_id.condition
        reached = (condition == "higher" and new_value >= self.target_goal) or (
            condition == "lower" and new_value <= self.target_goal
        )

        if reached:
            # success, do not set closed as it can still change
            if self.state != "reached":
                result["state"] = "reached"
        elif self.end_date and fields.Date.today() > self.end_date:
            # deadline passed without the target being met
            result["state"] = "failed"
            result["closed"] = True
        elif self.state == "reached":
            # the value fell back below the target before the deadline, so the
            # goal is in progress again — matching what ``action_reach``
            # documents ("will be reset to In Progress at the next goal update
            # until the end date").
            result["state"] = "inprogress"

        return {self: result} if result else {}

    def update_goal(self) -> bool:
        """Update the goals to recomputes values and change of states

        If a manual goal is not updated for enough time, the user will be
        reminded to do so (done only once, in 'inprogress' state).
        If a goal reaches the target value, the status is set to reached
        If the end date is passed (at least +1 day, time not considered) without
        the target value being reached, the goal is set as failed.
        """
        goals_by_definition = {}
        for goal in self.with_context(prefetch_fields=False):
            goals_by_definition.setdefault(goal.definition_id, []).append(goal)

        for definition, goals in goals_by_definition.items():
            goals_to_write = {}
            if definition.computation_mode == "manually":
                for goal in goals:
                    goals_to_write[goal] = goal._check_remind_delay()
            elif definition.computation_mode == "python":
                # TODO batch execution
                for goal in goals:
                    # execute the chosen method
                    cxt = {
                        "object": goal,
                        "env": self.env,
                        "date": date,
                        "datetime": datetime,
                        "timedelta": timedelta,
                        "time": time,
                    }
                    code = definition.compute_code.strip()
                    safe_eval(code, cxt, mode="exec")
                    # the result of the evaluated code is put in the 'result' local variable, propagated to the context
                    result = cxt.get("result")
                    if isinstance(result, (float, int)):
                        goals_to_write.update(goal._get_write_values(result))
                    else:
                        _logger.error(
                            "Invalid return content '%r' from the evaluation "
                            "of code for definition %s, expected a number",
                            result,
                            definition.name,
                        )

            elif definition.computation_mode in ("count", "sum"):  # count or sum
                # sudo: a count/sum goal measures an objective metric; under
                # the caller's record rules the stored value would depend on
                # who triggered the refresh (and pair badly with the sudo
                # write below). Scoping still comes from the goal's own
                # domain/batch_user_expression, not from the acting user.
                Obj = self.env[definition.model_id.model].sudo()

                field_date_name = definition.field_date_id.name
                if definition.batch_mode:
                    # batch mode, trying to do as much as possible in one request
                    general_domain = ast.literal_eval(definition.domain)
                    field_name = definition.batch_distinctive_field.name
                    subqueries = {}
                    for goal in goals:
                        start_date = (field_date_name and goal.start_date) or False
                        end_date = (field_date_name and goal.end_date) or False
                        subqueries.setdefault((start_date, end_date), {}).update(
                            {
                                goal.id: safe_eval(
                                    definition.batch_user_expression,
                                    {"user": goal.user_id},
                                )
                            }
                        )

                    # the global query should be split by time periods (especially for recurrent goals)
                    for (start_date, end_date), query_goals in subqueries.items():
                        subquery_domain = list(general_domain)
                        subquery_domain.append(
                            (field_name, "in", list(set(query_goals.values())))
                        )
                        if start_date:
                            subquery_domain.append((field_date_name, ">=", start_date))
                        if end_date:
                            subquery_domain.append((field_date_name, "<=", end_date))

                        if definition.computation_mode == "count":
                            user_values = Obj._read_group(
                                subquery_domain,
                                groupby=[field_name],
                                aggregates=["__count"],
                            )

                        else:  # sum
                            value_field_name = definition.field_id.name
                            user_values = Obj._read_group(
                                subquery_domain,
                                groupby=[field_name],
                                aggregates=[f"{value_field_name}:sum"],
                            )

                        # user_values has format of _read_group: [(<key>, <aggregate>), ...]
                        # _read_group emits no row for a key with zero matches,
                        # so build a lookup and default missing goals to 0 —
                        # otherwise a goal whose value dropped to 0 would keep
                        # its stale (possibly still 'reached') value.
                        value_by_key = {
                            (
                                field_value.id
                                if isinstance(field_value, models.Model)
                                else field_value
                            ): aggregate
                            for field_value, aggregate in user_values
                        }
                        for goal in [g for g in goals if g.id in query_goals]:
                            new_value = value_by_key.get(query_goals[goal.id], 0)
                            goals_to_write.update(goal._get_write_values(new_value))

                else:
                    field_name = definition.field_id.name
                    field = Obj._fields.get(field_name)
                    sum_supported = bool(field) and field.type in {
                        "integer",
                        "float",
                        "monetary",
                    }
                    if definition.computation_mode == "sum" and not sum_supported:
                        # Deliberate, upstream-tested behaviour: summing a
                        # non-numeric field degrades to counting matching rows
                        # (see test_40_create_challenge_with_sum_goal, which
                        # asserts the field is non-numeric on purpose).  Logged
                        # because it is surprising when hit by accident.
                        _logger.info(
                            "Goal definition %s sums %r on %s, which is not "
                            "numeric (type %r): counting rows instead.",
                            definition.name,
                            field_name,
                            definition.model_id.model,
                            field.type if field else None,
                        )
                    for goal in goals:
                        # eval the domain with user replaced by goal user object
                        domain = safe_eval(definition.domain, {"user": goal.user_id})

                        # add temporal clause(s) to the domain if fields are filled on the goal
                        if goal.start_date and field_date_name:
                            domain.append((field_date_name, ">=", goal.start_date))
                        if goal.end_date and field_date_name:
                            domain.append((field_date_name, "<=", goal.end_date))

                        if definition.computation_mode == "sum" and sum_supported:
                            res = Obj._read_group(
                                domain,
                                [],
                                [f"{field_name}:{definition.computation_mode}"],
                            )
                            new_value = res[0][0] or 0.0

                        else:  # computation mode = count
                            new_value = Obj.search_count(domain)

                        goals_to_write.update(goal._get_write_values(new_value))

            else:
                _logger.error(
                    "Invalid computation mode '%s' in definition %s",
                    definition.computation_mode,
                    definition.name,
                )

            # Batch writes: group goals by identical values dict
            by_values: dict[frozenset, list[int]] = {}
            for goal, values in goals_to_write.items():
                if not values:
                    continue
                key = frozenset(values.items())
                by_values.setdefault(key, []).append(goal.id)
            # The values above are computed server-side, never user-supplied,
            # so write as sudo: the refresh button must keep working for
            # non-manager users without tripping the automatic-goal write
            # guard, which only targets direct user writes of current/state.
            Goal = self.env["gamification.goal"].sudo()
            for vals_key, goal_ids in by_values.items():
                Goal.browse(goal_ids).write(dict(vals_key))
            if self.env.context.get("commit_gamification"):
                self.env.cr.commit()
        return True

    def action_start(self) -> bool:
        """Mark a goal as started.

        This should only be used when creating goals manually (in draft state)
        """
        self.write({"state": "inprogress"})
        return self.update_goal()

    def action_reach(self) -> bool:
        """Mark a goal as reached.

        If the target goal condition is not met, the state will be reset to In
        Progress at the next goal update until the end date.
        """
        return self.write({"state": "reached"})

    def action_fail(self) -> bool:
        """Set the state of the goal to failed.

        A failed goal will be ignored in future checks.
        """
        return self.write({"state": "failed"})

    def action_cancel(self) -> bool:
        """Reset the completion after setting a goal as reached or failed.

        This is only the current state, if the date and/or target criteria
        match the conditions for a change of state, this will be applied at the
        next goal update.
        """
        return self.write({"state": "inprogress"})

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        return super(GamificationGoal, self.with_context(no_remind_goal=True)).create(
            vals_list
        )

    def write(self, vals: ValuesType) -> Literal[True]:
        """Update goals and trigger on-change reports.

        Sets ``last_update`` to today.  If ``current`` changed and the
        challenge's report frequency is 'onchange', a single progress report
        is generated per challenge (batched, not per-goal).

        :raises UserError: if ``definition_id`` or ``user_id`` is modified on
            a non-draft goal (prevents drag-and-drop reordering accidents).
        """
        if "definition_id" in vals or "user_id" in vals:
            if any(g.state != "draft" for g in self):
                raise exceptions.UserError(
                    _("Can not modify the configuration of a started goal")
                )

        # Automatic goals (count/sum/python) are computed by the challenge cron.
        # Only managers/system may write their value or state directly; a regular
        # employee could otherwise force their own goal to 'reached' and trigger
        # challenge rewards.  Manual goals remain user-updatable (their whole point).
        if ("current" in vals or "state" in vals) and not (
            self.env.su or self.env.user.has_group("base.group_erp_manager")
        ):
            automatic = self.filtered(
                lambda g: g.definition_id.computation_mode != "manually"
            )
            if automatic:
                raise exceptions.UserError(
                    _(
                        "Automatic goals are computed by the system and can not be"
                        " updated manually."
                    )
                )

        vals["last_update"] = fields.Date.context_today(self)
        result = super().write(vals)

        # Batch on-change reports: one report per (challenge, user) pair
        if "current" in vals and "no_remind_goal" not in self.env.context:
            reports_to_send: dict = {}  # {challenge_id: set of user recordsets}
            for goal in self:
                challenge = goal.challenge_id
                if challenge and challenge.report_message_frequency == "onchange":
                    reports_to_send.setdefault(challenge.id, (challenge, set()))
                    reports_to_send[challenge.id][1].add(goal.user_id.id)
            for challenge, user_ids in reports_to_send.values():
                users = self.env["res.users"].browse(user_ids)
                challenge.sudo().report_progress(users=users)

        return result

    def get_action(self) -> dict[str, Any] | Literal[False]:
        """Get the ir.action related to update the goal

        In case of a manual goal, should return a wizard to update the value
        :return: action description in a dictionary
        """
        if self.definition_id.action_id:
            # open the action linked to the goal
            action = self.definition_id.action_id.read()[0]

            if self.definition_id.res_id_field:
                action["res_id"] = safe_eval(
                    self.definition_id.res_id_field, {"user": self.env.user}
                )

                # if one element to display, should see it in form mode if possible
                action["views"] = [
                    (view_id, mode)
                    for (view_id, mode) in action["views"]
                    if mode == "form"
                ] or action["views"]
            return action

        if self.computation_mode == "manually":
            # open a wizard window to update the value manually
            return {
                "name": _("Update %s", self.definition_id.name),
                "id": self.id,
                "type": "ir.actions.act_window",
                "views": [[False, "form"]],
                "target": "new",
                "context": {
                    "default_goal_id": self.id,
                    "default_current": self.current,
                },
                "res_model": "gamification.goal.wizard",
            }

        return False

    def _mail_get_partner_fields(self, introspect_fields: bool = False) -> list[str]:
        return ["user_partner_id"]

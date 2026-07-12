import ast
import json
from collections import defaultdict
from typing import Any, Self

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command, Domain
from odoo.libs.numbers import float_utils
from odoo.tools import SQL, LazyTranslate, formatLang, get_lang
from odoo.tools.cache_version import versioned_envelope
from odoo.tools.misc import unquote
from odoo.tools.translate import _

from .project_task import CLOSED_STATES
from .project_update import STATUS_COLOR
from odoo.addons.mail.tools.discuss import Store
from odoo.addons.rating.models import rating_data

_lt = LazyTranslate(__name__)


class ProjectProject(models.Model):
    _name = "project.project"
    _description = "Project"
    _inherit = [
        "analytic.plan.fields.mixin",
        "mail.activity.mixin",
        "mail.alias.mixin",
        "mail.tracking.duration.mixin",
        "portal.mixin",
        "rating.parent.mixin",
    ]
    _order = "sequence, name, id"
    _rating_satisfaction_days = 30  # takes 30 days by default
    _track_duration_field = "phase_id"

    # Explicit override: both rating.parent.mixin and mail.thread (via rating
    # module) define rating_ids.  The mail.thread version uses res_id/res_model
    # (ratings OF this record), but projects need the parent version that uses
    # parent_res_id/parent_res_model (ratings OF tasks BELONGING to this project).
    rating_ids = fields.One2many(
        "rating.rating",
        "parent_res_id",
        string="Ratings",
        bypass_search_access=True,
        domain=lambda self: [("parent_res_model", "=", self._name)],
        groups="base.group_user",
    )

    def __compute_task_count(
        self,
        count_field: str = "task_count",
        additional_domain: list | None = None,
    ) -> None:
        count_fields = {fname for fname in self._fields if "count" in fname}
        if count_field not in count_fields:
            raise ValueError(
                f"Parameter 'count_field' can only be one of {count_fields}, got {count_field} instead."
            )
        domain = Domain("project_id", "in", self.ids) & Domain(
            "is_template", "=", False
        )
        if additional_domain:
            domain &= Domain(additional_domain)
        ProjectTask = self.env["project.task"].with_context(
            active_test=any(project.active for project in self)
        )
        tasks_count_by_project = dict(
            ProjectTask._read_group(domain, ["project_id"], ["__count"])
        )
        for project in self:
            project.update({count_field: tasks_count_by_project.get(project, 0)})

    def _compute_task_count(self) -> None:
        self.__compute_task_count()

    def _compute_open_task_count(self) -> None:
        self.__compute_task_count(
            count_field="open_task_count",
            additional_domain=[("state", "in", self.env["project.task"].OPEN_STATES)],
        )

    def _compute_closed_task_count(self) -> None:
        self.__compute_task_count(
            count_field="closed_task_count",
            additional_domain=[("state", "in", [*CLOSED_STATES])],
        )

    def _default_phase_id(self) -> int | bool:
        # Since project stages are order by sequence first, this should fetch the one with the lowest sequence number.
        return self.env["project.phase"].search([], limit=1)

    @api.model
    def _search_is_favorite(self, operator: str, value: Any) -> list:
        if operator != "in":
            return NotImplemented
        return [("favorite_user_ids", "in", [self.env.uid])]

    def _compute_is_favorite(self) -> None:
        favorite_project_ids = self.env.user.favorite_project_ids
        for project in self:
            project.is_favorite = project in favorite_project_ids

    def _set_favorite_user_ids(self, is_favorite: bool) -> None:
        self_sudo = self.sudo()  # To allow project users to set projects as favorite
        if is_favorite:
            self_sudo.favorite_user_ids = [Command.link(self.env.uid)]
        else:
            self_sudo.favorite_user_ids = [Command.unlink(self.env.uid)]

    company_id = fields.Many2one(
        "res.company",
        string="Company",
        compute="_compute_company_id",
        inverse="_inverse_company_id",
        store=True,
        readonly=False,
    )
    currency_id = fields.Many2one(
        "res.currency",
        compute="_compute_currency_id",
        string="Currency",
        readonly=True,
        export_string_translation=False,
    )
    account_id = fields.Many2one(
        "account.analytic.account",
        copy=False,
        domain="['|', ('company_id', '=', False), ('company_id', '=?', company_id)]",
        ondelete="set null",
    )
    analytic_account_balance = fields.Monetary(
        related="account_id.balance",
    )
    partner_id = fields.Many2one(
        "res.partner",
        string="Customer",
        bypass_search_access=True,
        tracking=True,
        domain="['|', ('company_id', '=?', company_id), ('company_id', '=', False)]",
        index="btree_not_null",
    )
    resource_calendar_id = fields.Many2one(
        "resource.calendar",
        string="Working Time",
        compute="_compute_resource_calendar_id",
        export_string_translation=False,
    )
    user_id = fields.Many2one(
        "res.users",
        string="Project Manager",
        default=lambda self: self.env.user,
        tracking=True,
        falsy_value_label=_lt("👤 Unassigned"),
    )
    alias_id = fields.Many2one(
        help="Internal email associated with this project. Incoming emails are automatically synchronized "
        "with Tasks (or optionally Issues if the Issue Tracker module is installed)."
    )

    # Not `required` since this is an option to enable in project settings.
    phase_id = fields.Many2one(
        "project.phase",
        string="Phase",
        ondelete="restrict",
        groups="project.group_project_stages",
        tracking=True,
        index=True,
        copy=False,
        default=_default_phase_id,
        group_expand="_read_group_expand_full",
    )
    phase_color = fields.Integer(
        string="Phase Color",
        related="phase_id.color",
        export_string_translation=False,
    )

    name = fields.Char(
        "Name",
        index="trigram",
        required=True,
        tracking=True,
        translate=True,
        default_export_compatible=True,
    )
    active = fields.Boolean(default=True, copy=False, export_string_translation=False)
    sequence = fields.Integer(default=10, export_string_translation=False)
    description = fields.Html(
        help="Description to provide more information and context about this project"
    )
    label_tasks = fields.Char(
        string="Use Tasks as",
        default=lambda s: s.env._("Tasks"),
        translate=True,
        help="Name used to refer to the tasks of your project e.g. tasks, tickets, sprints, etc...",
    )
    color = fields.Integer(string="Color Index", export_string_translation=False)
    duration_tracking = fields.Json(groups="project.group_project_stages")
    date_start = fields.Date(string="Start Date", copy=False)
    # TODO LMMG migrate all references from 'date' to 'date_end', then make
    #  date_end the canonical stored field and date the related alias.
    date = fields.Date(
        string="Expiration Date",
        copy=False,
        index=True,
        tracking=True,
        help="Date on which this project ends. The timeframe defined on the project is taken into account when viewing its planning.",
    )
    date_end = fields.Date(related="date", string="End Date", readonly=False)

    # Project settings
    privacy_visibility = fields.Selection(
        [
            ("followers", "Invited internal users"),
            ("invited_users", "Invited internal and portal users"),
            ("employees", "All internal users"),
            ("portal", " All internal users and invited portal users"),
        ],
        string="Visibility",
        required=True,
        default="portal",
        tracking=True,
        help="Project and Task Visibility:\n"
        "- Invited internal users: Can access only the project or tasks they follow. Assignees automatically get access.\n"
        "- Invited internal and portal users: Same as above, extended to portal users.\n"
        "- All internal users: Full access to the project and all its tasks.\n"
        "- All internal and invited portal users: Internal users get full access. Portal users can access only the project or tasks they follow.\n\n"
        "Portal Access Levels:\n"
        "- Read-only: Portal users see tasks via their portal but can’t edit them.\n"
        "- Edit (limited): Portal users access kanban/list views and can edit limited fields on followed tasks.\n"
        "- Edit: Same as above, with access to all tasks.\n\n"
        "Other Rules:\n"
        "- Internal users can open a task from a direct link, even without project access.\n"
        "- Project admins have access to private projects, even if not followers.\n",
    )
    privacy_visibility_warning = fields.Char(
        "Privacy Visibility Warning",
        compute="_compute_privacy_visibility_warning",
        export_string_translation=False,
    )
    access_instruction_message = fields.Char(
        "Access Instruction Message",
        compute="_compute_access_instruction_message",
        export_string_translation=False,
    )
    allow_dependencies = fields.Boolean(
        "Task Dependencies",
        inverse="_inverse_allow_dependencies",
    )
    allow_milestones = fields.Boolean(
        "Milestones",
        inverse="_inverse_allow_milestones",
    )
    allow_recurring_tasks = fields.Boolean(
        "Recurring Tasks",
        inverse="_inverse_allow_recurring_tasks",
    )
    use_sprints = fields.Boolean(
        "Use Sprints",
        help="Enable time-boxed iterations for this project.",
    )

    # Sprint fields
    sprint_ids = fields.One2many(
        "project.sprint",
        "project_id",
        string="Sprints",
        export_string_translation=False,
    )
    active_sprint_id = fields.Many2one(
        "project.sprint",
        string="Active Sprint",
        compute="_compute_active_sprint_id",
        export_string_translation=False,
    )
    sprint_count = fields.Integer(
        "Sprint Count",
        compute="_compute_sprint_count",
        export_string_translation=False,
    )

    tag_ids = fields.Many2many(
        "project.tags",
        relation="project_project_project_tags_rel",
        string="Tags",
    )
    favorite_user_ids = fields.Many2many(
        "res.users",
        "project_favorite_user_rel",
        "project_id",
        "user_id",
        string="Members",
        export_string_translation=False,
        copy=False,
    )
    is_favorite = fields.Boolean(
        compute="_compute_is_favorite",
        readonly=False,
        search="_search_is_favorite",
        compute_sudo=True,
        string="Show Project on Dashboard",
        export_string_translation=False,
    )
    workflow_step_ids = fields.Many2many(
        "project.workflow.step",
        "project_workflow_step_project_rel",
        "project_id",
        "step_id",
        string="Workflow Steps",
        export_string_translation=False,
    )
    tasks = fields.One2many(
        "project.task",
        "project_id",
        string="Task Activities",
    )
    task_ids = fields.One2many(
        "project.task",
        "project_id",
        string="Tasks",
        export_string_translation=False,
        domain="[('is_closed', '=', False)]",
    )
    task_properties_definition = fields.PropertiesDefinition("Task Properties")
    task_count = fields.Integer(
        compute="_compute_task_count",
        string="Task Count",
        export_string_translation=False,
    )
    open_task_count = fields.Integer(
        compute="_compute_open_task_count",
        string="Open Task Count",
        export_string_translation=False,
    )
    closed_task_count = fields.Integer(
        compute="_compute_closed_task_count",
        export_string_translation=False,
    )
    task_completion_percentage = fields.Float(
        compute="_compute_task_completion_percentage",
        export_string_translation=False,
    )

    # Project Sharing fields
    collaborator_ids = fields.One2many(
        "project.collaborator",
        "project_id",
        string="Collaborators",
        copy=False,
        export_string_translation=False,
    )
    collaborator_count = fields.Integer(
        "# Collaborators",
        compute="_compute_collaborator_count",
        compute_sudo=True,
        export_string_translation=False,
    )

    # Update fields
    update_ids = fields.One2many(
        "project.update",
        "project_id",
        export_string_translation=False,
    )
    update_count = fields.Integer(
        compute="_compute_total_update_ids",
        export_string_translation=False,
    )
    last_update_id = fields.Many2one(
        "project.update",
        string="Last Update",
        copy=False,
        export_string_translation=False,
    )
    last_update_status = fields.Selection(
        selection=[
            ("on_track", "On Track"),
            ("at_risk", "At Risk"),
            ("off_track", "Off Track"),
            ("on_hold", "On Hold"),
            ("to_define", "Set Status"),
            ("done", "Complete"),
        ],
        default="to_define",
        compute="_compute_last_update_status",
        store=True,
        readonly=False,
        required=True,
        export_string_translation=False,
    )
    last_update_color = fields.Integer(
        compute="_compute_last_update_color",
        export_string_translation=False,
    )

    # Milestone fields
    milestone_ids = fields.One2many(
        "project.milestone",
        "project_id",
        copy=True,
        export_string_translation=False,
    )
    milestone_count = fields.Integer(
        compute="_compute_milestone_count",
        groups="project.group_project_milestone",
        export_string_translation=False,
    )
    milestone_count_reached = fields.Integer(
        compute="_compute_milestone_reached_count",
        groups="project.group_project_milestone",
        export_string_translation=False,
    )
    is_milestone_exceeded = fields.Boolean(
        compute="_compute_is_milestone_exceeded",
        search="_search_is_milestone_exceeded",
        export_string_translation=False,
    )
    milestone_progress = fields.Integer(
        "Milestones Reached",
        compute="_compute_milestone_reached_count",
        groups="project.group_project_milestone",
        export_string_translation=False,
    )
    next_milestone_id = fields.Many2one(
        "project.milestone",
        compute="_compute_next_milestone_id",
        groups="project.group_project_milestone",
        export_string_translation=False,
    )
    can_mark_milestone_as_done = fields.Boolean(
        compute="_compute_next_milestone_id",
        groups="project.group_project_milestone",
        export_string_translation=False,
    )
    is_milestone_deadline_exceeded = fields.Boolean(
        compute="_compute_next_milestone_id",
        groups="project.group_project_milestone",
        export_string_translation=False,
    )

    # ── Benefits Realization ────────────────────────────────────────
    benefit_ids = fields.One2many(
        "project.benefit",
        "project_id",
        string="Benefits",
        export_string_translation=False,
    )
    benefit_count = fields.Integer(
        "Benefit Count",
        compute="_compute_benefit_count",
        export_string_translation=False,
    )

    # ── Baselines ────────────────────────────────────────────────────
    baseline_ids = fields.One2many(
        "project.baseline",
        "project_id",
        string="Baselines",
        export_string_translation=False,
    )
    current_baseline_id = fields.Many2one(
        "project.baseline",
        string="Current Baseline",
        compute="_compute_current_baseline_id",
        export_string_translation=False,
    )

    # ── Gate Reviews ─────────────────────────────────────────────────
    gate_ids = fields.One2many(
        "project.gate",
        "project_id",
        string="Gate Reviews",
        export_string_translation=False,
    )
    gate_count = fields.Integer(
        "Gates",
        compute="_compute_gate_count",
        export_string_translation=False,
    )

    # ── Project History ──────────────────────────────────────────────
    history_ids = fields.One2many(
        "project.history",
        "project_id",
        string="History Records",
        export_string_translation=False,
    )

    # ── Pre-Mortem ───────────────────────────────────────────────────
    # Klein (1998): +30% cause identification vs standard risk identification.
    premortem_done = fields.Boolean(
        "Pre-Mortem Conducted",
        help="Was a pre-mortem exercise conducted at project kickoff?",
    )
    premortem_date = fields.Date("Pre-Mortem Date")
    premortem_participants = fields.Many2many(
        "res.users",
        "project_premortem_participants_rel",
        "project_id",
        "user_id",
        string="Pre-Mortem Participants",
    )
    premortem_notes = fields.Html(
        "Pre-Mortem Notes",
        help="'Imagine this project has failed. Why?' — capture all identified failure modes.",
    )

    # ── Retrospectives ─────────────────────────────────────────────
    retrospective_ids = fields.One2many(
        "project.retrospective",
        "project_id",
        string="Retrospectives",
        export_string_translation=False,
    )
    retrospective_count = fields.Integer(
        "Retrospective Count",
        compute="_compute_retrospective_count",
        export_string_translation=False,
    )

    # ── Health Indicators ──────────────────────────────────────────
    # Computed from objective data to prevent status theater.
    health_score = fields.Integer(
        "Health Score",
        compute="_compute_health_indicators",
        help="Composite 0-100 score based on deadlines, milestones, risk, and staleness.",
        export_string_translation=False,
    )
    health_status = fields.Selection(
        [
            ("healthy", "Healthy"),
            ("attention", "Needs Attention"),
            ("warning", "Warning"),
            ("critical", "Critical"),
        ],
        string="Health",
        compute="_compute_health_indicators",
        help="Derived from health_score: healthy (80-100), attention (60-79), warning (40-59), critical (0-39).",
        export_string_translation=False,
    )

    # ── Risk Register ────────────────────────────────────────────────
    risk_ids = fields.One2many(
        "project.risk",
        "project_id",
        string="Risks",
        export_string_translation=False,
    )
    risk_count = fields.Integer(
        "Risk Count",
        compute="_compute_risk_count",
        export_string_translation=False,
    )
    high_risk_count = fields.Integer(
        "High/Critical Risks",
        compute="_compute_risk_count",
        export_string_translation=False,
    )

    # ── Flow Metrics ─────────────────────────────────────────────────
    # Aggregated from task-level data. See gap_analysis_code.md §1.
    wip_count = fields.Integer(
        "WIP Count",
        compute="_compute_flow_metrics",
        help="Number of open, non-blocked tasks.",
        export_string_translation=False,
    )
    avg_lead_time = fields.Float(
        "Avg Lead Time (hours)",
        compute="_compute_flow_metrics",
        digits=(16, 1),
        help="Average working hours from creation to closure (last 90 days). "
        "Includes queue wait time.",
        export_string_translation=False,
    )
    avg_cycle_time = fields.Float(
        "Avg Cycle Time (hours)",
        compute="_compute_flow_metrics",
        digits=(16, 1),
        help="Average working hours from assignment to closure (last 90 days). "
        "Excludes queue wait time.",
        export_string_translation=False,
    )
    throughput_week = fields.Float(
        "Throughput / Week",
        compute="_compute_flow_metrics",
        digits=(16, 1),
        help="Tasks closed per week (rolling 4-week average).",
        export_string_translation=False,
    )
    deadline_compliance_pct = fields.Float(
        "Deadline Compliance %",
        compute="_compute_flow_metrics",
        digits=(5, 1),
        help="Percentage of closed tasks with deadlines that met their deadline.",
        export_string_translation=False,
    )

    is_template = fields.Boolean(
        copy=False,
        export_string_translation=False,
    )
    show_ratings = fields.Boolean(
        compute="_compute_show_ratings",
        export_string_translation=False,
    )

    _project_date_greater = models.Constraint(
        "check(date >= date_start)",
        "The project's start date must be before its end date.",
    )

    @api.onchange("company_id")
    def _onchange_company_id(self) -> None:
        if (
            self.env.user.has_group("project.group_project_stages")
            and self.phase_id.company_id
            and self.phase_id.company_id != self.company_id
        ):
            self.phase_id = (
                self.env["project.phase"]
                .search(
                    [("company_id", "in", [self.company_id.id, False])],
                    order=f"sequence asc, {self.env['project.phase']._order}",
                    limit=1,
                )
                .id
            )

    @api.depends("milestone_ids", "milestone_ids.is_reached", "milestone_ids.deadline")
    def _compute_next_milestone_id(self) -> None:
        milestones_per_project_id = {
            project.id: milestones
            for project, milestones in self.env["project.milestone"]._read_group(
                [("project_id", "in", self.ids), ("is_reached", "=", False)],
                ["project_id"],
                ["id:recordset"],
            )
        }
        milestones = self.env["project.milestone"].concat(
            *milestones_per_project_id.values()
        )
        task_read_group = self.env["project.task"]._read_group(
            [("milestone_id", "in", milestones.ids)],
            ["milestone_id", "state"],
            ["__count"],
        )
        task_count_per_milestones = defaultdict(lambda: (0, 0))
        for milestone, state, count in task_read_group:
            opened_task_count, closed_task_count = task_count_per_milestones[
                milestone.id
            ]
            if state in CLOSED_STATES:
                closed_task_count += count
            else:
                opened_task_count += count
            task_count_per_milestones[milestone.id] = (
                opened_task_count,
                closed_task_count,
            )
        for project in self:
            milestones = milestones_per_project_id.get(
                project.id, self.env["project.milestone"]
            )
            project.next_milestone_id = milestones[:1]
            milestone_deadline_exceeded = False
            milestone_marked_as_done = False
            for m in milestones:
                opened_task_count, closed_task_count = task_count_per_milestones[m.id]
                if (
                    not milestone_deadline_exceeded
                    and m.is_deadline_exceeded
                    and (opened_task_count > 0 or closed_task_count == 0)
                ):
                    milestone_deadline_exceeded = True
                    break
                if (
                    not milestone_marked_as_done
                    and opened_task_count == 0
                    and closed_task_count > 0
                ):
                    milestone_marked_as_done = True
            project.is_milestone_deadline_exceeded = milestone_deadline_exceeded
            project.can_mark_milestone_as_done = milestone_marked_as_done

    @api.depends("sprint_ids", "sprint_ids.state")
    def _compute_active_sprint_id(self) -> None:
        """Find the currently active sprint for each project."""
        for project in self:
            project.active_sprint_id = project.sprint_ids.filtered(
                lambda s: s.state == "active"
            )[:1]

    @api.depends("sprint_ids")
    def _compute_sprint_count(self) -> None:
        """Count sprints per project."""
        for project in self:
            project.sprint_count = len(project.sprint_ids)

    @api.depends("benefit_ids")
    def _compute_benefit_count(self) -> None:
        """Count benefits per project."""
        for project in self:
            project.benefit_count = len(project.benefit_ids)

    @api.depends("baseline_ids", "baseline_ids.is_current")
    def _compute_current_baseline_id(self) -> None:
        """Find the current baseline for each project."""
        for project in self:
            project.current_baseline_id = project.baseline_ids.filtered("is_current")[
                :1
            ]

    @api.depends("gate_ids")
    def _compute_gate_count(self) -> None:
        """Count gate reviews per project."""
        for project in self:
            project.gate_count = len(project.gate_ids)

    def action_archive_to_history(self) -> None:
        """Create a project.history record from this project's current state."""
        self.ensure_one()
        self.env["project.history"].create_from_project(self)

    def action_compute_critical_path(self) -> None:
        """Compute the critical path with all four dependency types and calendar dates.

        Handles FS, SS, FF, SF dependency types per PMI definitions:
        - FS: successor.ES = max(predecessor.EF + lag)
        - SS: successor.ES = max(predecessor.ES + lag)
        - FF: successor.EF = max(predecessor.EF + lag) -> ES = EF - duration
        - SF: successor.EF = max(predecessor.ES + lag) -> ES = EF - duration

        After computing abstract-hour positions, converts to real calendar
        dates using the project's resource calendar.
        """
        self.ensure_one()
        tasks = self.env["project.task"].search(
            [
                ("project_id", "=", self.id),
                ("is_template", "=", False),
                ("state", "not in", list(CLOSED_STATES)),
            ]
        )
        if not tasks:
            return

        task_set = set(tasks.ids)
        Dep = self.env["project.task.dependency"]
        typed_deps = Dep.search([("project_id", "=", self.id)])

        # Dependency data per task: predecessors with type and lag
        deps_on: dict[int, list[tuple[int, str, float]]] = defaultdict(list)
        successors_of: dict[int, list[int]] = defaultdict(list)

        if typed_deps:
            for dep in typed_deps:
                tid = dep.task_id.id
                pred_id = dep.depends_on_id.id
                if tid in task_set and pred_id in task_set:
                    deps_on[tid].append((pred_id, dep.dependency_type, dep.lag_hours))
                    successors_of[pred_id].append(tid)
        else:
            for task in tasks:
                for pred in task.predecessor_ids:
                    if pred.id in task_set:
                        deps_on[task.id].append((pred.id, "fs", 0.0))
                        successors_of[pred.id].append(task.id)

        duration = {t.id: t.allocated_hours or 0.0 for t in tasks}

        # Guard against dependency cycles before running the passes: forward()
        # and backward() are plain recursive DFS and would recurse forever
        # (RecursionError → HTTP 500) on a cyclic graph. Dependencies are
        # user-editable and not otherwise constrained to a DAG, so detect a
        # back-edge with an iterative three-colour DFS and fail cleanly.
        _UNVISITED, _IN_STACK, _DONE = 0, 1, 2
        color = dict.fromkeys(task_set, _UNVISITED)
        for root in task_set:
            if color[root] != _UNVISITED:
                continue
            dfs_stack: list[tuple[int, int]] = [(root, 0)]
            while dfs_stack:
                node, idx = dfs_stack[-1]
                color[node] = _IN_STACK
                preds = deps_on[node]
                if idx < len(preds):
                    dfs_stack[-1] = (node, idx + 1)
                    pred_id = preds[idx][0]
                    if color.get(pred_id) == _IN_STACK:
                        raise UserError(
                            self.env._(
                                "A dependency cycle was detected among the tasks "
                                "of project %(project)s. Resolve the circular "
                                "dependency before computing the critical path.",
                                project=self.display_name,
                            )
                        )
                    if color.get(pred_id, _UNVISITED) == _UNVISITED:
                        dfs_stack.append((pred_id, 0))
                else:
                    color[node] = _DONE
                    dfs_stack.pop()

        # Forward pass
        es: dict[int, float] = {}
        ef: dict[int, float] = {}

        def forward(tid: int) -> None:
            """Compute earliest start/finish for a task."""
            if tid in ef:
                return
            if not deps_on[tid]:
                es[tid] = 0.0
                ef[tid] = duration[tid]
                return
            for pred_id, _dtype, _lag in deps_on[tid]:
                forward(pred_id)
            max_es = 0.0
            max_ef_constraint = 0.0
            has_ef_constraint = False
            for pred_id, dtype, lag in deps_on[tid]:
                if dtype == "fs":
                    max_es = max(max_es, ef[pred_id] + lag)
                elif dtype == "ss":
                    max_es = max(max_es, es[pred_id] + lag)
                elif dtype == "ff":
                    max_ef_constraint = max(max_ef_constraint, ef[pred_id] + lag)
                    has_ef_constraint = True
                elif dtype == "sf":
                    max_ef_constraint = max(max_ef_constraint, es[pred_id] + lag)
                    has_ef_constraint = True
            if has_ef_constraint:
                es_from_ef = max_ef_constraint - duration[tid]
                max_es = max(max_es, es_from_ef)
            es[tid] = max_es
            ef[tid] = es[tid] + duration[tid]

        for t in tasks:
            forward(t.id)

        project_end = max(ef.values()) if ef else 0.0

        # Backward pass
        lf: dict[int, float] = {}
        ls_map: dict[int, float] = {}

        def backward(tid: int) -> None:
            """Compute latest start/finish for a task."""
            if tid in ls_map:
                return
            if not successors_of[tid]:
                lf[tid] = project_end
            else:
                for succ_id in successors_of[tid]:
                    backward(succ_id)
                lf[tid] = project_end
                for succ_id in successors_of[tid]:
                    for pred_id, dtype, lag in deps_on[succ_id]:
                        if pred_id != tid:
                            continue
                        if dtype == "fs":
                            lf[tid] = min(lf[tid], ls_map[succ_id] - lag)
                        elif dtype == "ss":
                            lf[tid] = min(
                                lf[tid], ls_map[succ_id] - lag + duration[tid]
                            )
                        elif dtype == "ff":
                            lf[tid] = min(lf[tid], lf[succ_id] - lag)
                        elif dtype == "sf":
                            lf[tid] = min(lf[tid], lf[succ_id] - lag + duration[tid])
            ls_map[tid] = lf[tid] - duration[tid]

        for t in tasks:
            backward(t.id)

        # Convert abstract hours to calendar dates and write results
        calendar = self.resource_calendar_id
        now = fields.Datetime.now()
        for task in tasks:
            tid = task.id
            es_h = es.get(tid, 0.0)
            ls_h = ls_map.get(tid, 0.0)
            total_fl = ls_h - es_h
            planned_start = calendar.plan_hours(es_h, now) if es_h else now
            planned_end = (
                calendar.plan_hours(ef.get(tid, 0.0), now) if ef.get(tid) else now
            )
            ls_dt = calendar.plan_hours(ls_h, now) if ls_h else now
            task.write(
                {
                    "earliest_start": planned_start,
                    "latest_start": ls_dt,
                    "total_float": total_fl,
                    "is_critical_path": abs(total_fl) < 0.01,
                    "planned_date_start": planned_start,
                    "planned_date_end": planned_end,
                }
            )

    def action_level_resources(self) -> None:
        """Basic resource leveling: shift non-critical tasks to avoid overallocation.

        Algorithm:
        1. Run CPM first to establish planned dates.
        2. Build per-user timeline from planned_date_start/end.
        3. For each non-critical task (sorted by float descending):
           if assigned user is overloaded in the planned window,
           shift planned_date_start forward to next available slot.
        4. Recompute dependent tasks' dates after each shift.

        This is a heuristic, not an optimization solver.
        """
        self.ensure_one()
        # Step 1: compute CPM to establish baseline dates
        self.action_compute_critical_path()

        calendar = self.resource_calendar_id
        tasks = self.env["project.task"].search(
            [
                ("project_id", "=", self.id),
                ("is_template", "=", False),
                ("state", "not in", list(CLOSED_STATES)),
                ("planned_date_start", "!=", False),
                ("planned_date_end", "!=", False),
            ]
        )
        if not tasks:
            return

        # Sort: process tasks with most float first (most flexible)
        leveling_order = sorted(
            tasks.filtered(lambda t: not t.is_critical_path),
            key=lambda t: -(t.total_float or 0.0),
        )

        # Build per-user allocation map: user_id -> list of (start, end, hours)
        user_slots: dict[int, list[tuple]] = defaultdict(list)
        for task in tasks:
            for user in task.user_ids:
                user_slots[user.id].append(
                    (
                        task.planned_date_start,
                        task.planned_date_end,
                        task.allocated_hours or 0.0,
                        task.id,
                    )
                )

        # Heuristic: check if user has > 8h/day in any overlapping window
        for task in leveling_order:
            if not task.user_ids or not task.allocated_hours:
                continue
            for user in task.user_ids:
                slots = user_slots[user.id]
                # Count concurrent hours in task's window
                concurrent = sum(
                    s[2]
                    for s in slots
                    if s[3] != task.id
                    and s[0] < task.planned_date_end
                    and s[1] > task.planned_date_start
                )
                if concurrent <= 0:
                    continue
                # Find latest end among overlapping tasks
                latest_end = max(
                    (
                        s[1]
                        for s in slots
                        if s[3] != task.id
                        and s[0] < task.planned_date_end
                        and s[1] > task.planned_date_start
                    ),
                    default=task.planned_date_start,
                )
                # Shift task to start after the overlap, respecting float
                max_shift_hours = task.total_float or 0.0
                new_start = (
                    calendar.plan_hours(task.allocated_hours, latest_end)
                    if latest_end
                    else task.planned_date_start
                )
                # Only shift if within float allowance
                shift_hours = (
                    new_start - task.planned_date_start
                ).total_seconds() / 3600
                if 0 < shift_hours <= max_shift_hours:
                    new_end = calendar.plan_hours(task.allocated_hours, new_start)
                    # Update slot tracking
                    user_slots[user.id] = [s for s in slots if s[3] != task.id] + [
                        (new_start, new_end, task.allocated_hours, task.id)
                    ]
                    task.write(
                        {
                            "planned_date_start": new_start,
                            "planned_date_end": new_end,
                        }
                    )

    @api.depends("retrospective_ids")
    def _compute_retrospective_count(self) -> None:
        """Count retrospectives per project."""
        retro_data = self.env["project.retrospective"]._read_group(
            [("project_id", "in", self.ids)],
            ["project_id"],
            ["__count"],
        )
        counts = {project.id: count for project, count in retro_data}
        for project in self:
            project.retrospective_count = counts.get(project.id, 0)

    def _compute_health_indicators(self) -> None:
        """Compute a composite health score from objective project data.

        Components (each 0-100, weighted equally):
        - Schedule: % of open tasks not past their deadline
        - Milestones: % of milestones on track (reached or deadline in future)
        - Risk: inverse of normalized risk exposure
        - Staleness: % of open tasks that are not rotting

        Intentionally has NO @api.depends: this aggregates across every task,
        milestone and risk of the project, so a reactive recompute would fire a
        full re-aggregation on any task edit. It is a per-read snapshot
        (recomputed once per environment / page load) — do not make it stored or
        add depends. Because it is non-reactive it also cannot be searched or
        grouped; expose a refresh action instead if live values are needed.
        """
        if not self.ids:
            self.health_score = 100
            self.health_status = "healthy"
            return

        # Compare against a naive-UTC "now"/"today" bound in Python. The task
        # timestamp columns store naive UTC; a bare SQL NOW()/CURRENT_DATE is a
        # timestamptz evaluated in the connection's session timezone (not UTC
        # here), which skews every "overdue"/"stale" comparison by the offset.
        now = self.env.cr.now()
        today = now.date()

        # These computes read via hand-written SQL and have no @api.depends, so
        # the ORM will not auto-flush pending task/milestone/risk writes first.
        # Flush explicitly, else the metrics read stale pre-write rows.
        self.env["project.task"].flush_model(
            ["project_id", "state", "date_end", "date_last_status_change",
             "create_date", "is_template", "active"]
        )
        self.env["project.milestone"].flush_model(
            ["project_id", "is_reached", "deadline"]
        )
        self.env["project.risk"].flush_model(["project_id", "risk_score", "active"])

        self.env.cr.execute(
            SQL(
                """
            SELECT
                t.project_id,
                -- Schedule: pct of open tasks with deadline that are not overdue
                CASE
                    WHEN COUNT(*) FILTER (
                        WHERE t.state NOT IN ('done', 'canceled')
                          AND t.date_end IS NOT NULL
                    ) = 0 THEN 100.0
                    ELSE 100.0 * COUNT(*) FILTER (
                        WHERE t.state NOT IN ('done', 'canceled')
                          AND t.date_end IS NOT NULL
                          AND t.date_end >= %(now)s
                    ) / NULLIF(COUNT(*) FILTER (
                        WHERE t.state NOT IN ('done', 'canceled')
                          AND t.date_end IS NOT NULL
                    ), 0)
                END AS schedule_score,
                -- Staleness: pct of open tasks not rotting
                CASE
                    WHEN COUNT(*) FILTER (
                        WHERE t.state NOT IN ('done', 'canceled')
                    ) = 0 THEN 100.0
                    ELSE 100.0 * COUNT(*) FILTER (
                        WHERE t.state NOT IN ('done', 'canceled')
                          AND COALESCE(t.date_last_status_change, t.create_date)
                              >= %(now)s - INTERVAL '14 days'
                    ) / NULLIF(COUNT(*) FILTER (
                        WHERE t.state NOT IN ('done', 'canceled')
                    ), 0)
                END AS staleness_score
            FROM project_task t
            WHERE t.project_id IN %(project_ids)s
              AND t.is_template IS NOT TRUE
              AND t.active = TRUE
            GROUP BY t.project_id
            """,
                project_ids=tuple(self.ids),
                now=now,
            )
        )
        task_scores = {row[0]: (row[1], row[2]) for row in self.env.cr.fetchall()}

        # Milestone scores
        milestone_scores: dict[int, float] = {}
        if self.ids:
            self.env.cr.execute(
                SQL(
                    """
                SELECT
                    project_id,
                    CASE
                        WHEN COUNT(*) = 0 THEN 100.0
                        ELSE 100.0 * COUNT(*) FILTER (
                            WHERE is_reached
                               OR deadline IS NULL
                               OR deadline >= %(today)s
                        ) / COUNT(*)
                    END AS milestone_score
                FROM project_milestone
                WHERE project_id IN %(project_ids)s
                GROUP BY project_id
                """,
                    project_ids=tuple(self.ids),
                    today=today,
                )
            )
            milestone_scores = {row[0]: row[1] for row in self.env.cr.fetchall()}

        # Risk scores (from already-computed risk_count)
        risk_data: dict[int, int] = {}
        if self.ids:
            self.env.cr.execute(
                SQL(
                    """
                SELECT project_id, COALESCE(SUM(risk_score), 0)
                FROM project_risk
                WHERE project_id IN %(project_ids)s AND active = TRUE
                GROUP BY project_id
                """,
                    project_ids=tuple(self.ids),
                )
            )
            risk_data = dict(self.env.cr.fetchall())

        for project in self:
            schedule, staleness = task_scores.get(project.id, (100.0, 100.0))
            milestone = milestone_scores.get(project.id, 100.0)
            # Risk: convert total risk score to 0-100 where 0 risk = 100 health
            total_risk = risk_data.get(project.id, 0)
            # Normalize: 50+ total risk score = 0 health from risk component
            risk_health = max(0.0, 100.0 - total_risk * 2)

            score = int((schedule + staleness + milestone + risk_health) / 4)
            project.health_score = max(0, min(100, score))
            if score >= 80:
                project.health_status = "healthy"
            elif score >= 60:
                project.health_status = "attention"
            elif score >= 40:
                project.health_status = "warning"
            else:
                project.health_status = "critical"

    @api.depends("risk_ids", "risk_ids.risk_level", "risk_ids.active")
    def _compute_risk_count(self) -> None:
        """Count active risks and high/critical risks per project."""
        if not self.ids:
            self.risk_count = 0
            self.high_risk_count = 0
            return
        risk_data = self.env["project.risk"]._read_group(
            [("project_id", "in", self.ids), ("active", "=", True)],
            ["project_id", "risk_level"],
            ["__count"],
        )
        counts: dict[int, tuple[int, int]] = {}
        for project, risk_level, count in risk_data:
            total, high = counts.get(project.id, (0, 0))
            total += count
            if risk_level in ("high", "critical"):
                high += count
            counts[project.id] = (total, high)
        for project in self:
            total, high = counts.get(project.id, (0, 0))
            project.risk_count = total
            project.high_risk_count = high

    def _compute_flow_metrics(self) -> None:
        """Compute project-level flow metrics from task data.

        Uses direct SQL for performance — these are read-heavy analytics fields
        that aggregate across potentially thousands of tasks.

        Intentionally has NO @api.depends (see _compute_health_indicators): a
        per-read snapshot, not a reactive/stored field. Do not add depends.
        """
        if not self.ids:
            self.wip_count = 0
            self.avg_lead_time = 0.0
            self.avg_cycle_time = 0.0
            self.throughput_week = 0.0
            self.deadline_compliance_pct = 0.0
            return

        # Naive-UTC "now" bound in Python — see _compute_health_indicators: a
        # bare SQL NOW() is timezone-skewed against the naive-UTC columns.
        now = self.env.cr.now()

        # No @api.depends here, so flush pending task writes before the raw SQL.
        self.env["project.task"].flush_model(
            ["project_id", "state", "date_closed", "date_end",
             "lead_time_hours", "cycle_time_hours", "is_template", "active"]
        )

        self.env.cr.execute(
            SQL(
                """
            SELECT
                project_id,
                -- WIP: open non-blocked tasks
                COUNT(*) FILTER (
                    WHERE state NOT IN ('done', 'canceled', 'blocked')
                ) AS wip_count,
                -- Avg lead time: create→close (closed in last 90 days).
                -- NOTE: date_closed is the actual completion timestamp; date_end
                -- is the (renamed) deadline. Rolling windows must key off closure.
                AVG(lead_time_hours) FILTER (
                    WHERE state IN ('done', 'canceled')
                      AND date_closed >= %(now)s - INTERVAL '90 days'
                      AND lead_time_hours > 0
                ) AS avg_lead_time,
                -- Avg cycle time: assign→close (closed in last 90 days)
                AVG(cycle_time_hours) FILTER (
                    WHERE state IN ('done', 'canceled')
                      AND date_closed >= %(now)s - INTERVAL '90 days'
                      AND cycle_time_hours > 0
                ) AS avg_cycle_time,
                -- Throughput: tasks closed in last 28 days / 4
                COUNT(*) FILTER (
                    WHERE state IN ('done', 'canceled')
                      AND date_closed >= %(now)s - INTERVAL '28 days'
                ) / 4.0 AS throughput_week,
                -- Deadline compliance: pct of deadline-having closed tasks whose
                -- actual closure (date_closed) landed on or before the deadline.
                CASE
                    WHEN COUNT(*) FILTER (
                        WHERE state IN ('done', 'canceled')
                          AND date_end IS NOT NULL
                          AND date_closed IS NOT NULL
                    ) = 0 THEN 0.0
                    ELSE 100.0 * COUNT(*) FILTER (
                        WHERE state IN ('done', 'canceled')
                          AND date_end IS NOT NULL
                          AND date_closed IS NOT NULL
                          AND date_closed <= date_end
                    ) / COUNT(*) FILTER (
                        WHERE state IN ('done', 'canceled')
                          AND date_end IS NOT NULL
                          AND date_closed IS NOT NULL
                    )
                END AS deadline_compliance_pct
            FROM project_task
            WHERE project_id IN %(project_ids)s
              -- is_template has no default, so it is NULL (not FALSE) for normal
              -- tasks; `= FALSE` would wrongly exclude every non-template task.
              AND is_template IS NOT TRUE
              AND active = TRUE
            GROUP BY project_id
            """,
                project_ids=tuple(self.ids),
                now=now,
            )
        )
        results = {row[0]: row[1:] for row in self.env.cr.fetchall()}
        for project in self:
            wip, avg_lt, avg_ct, tp, dcp = results.get(
                project.id, (0, 0.0, 0.0, 0.0, 0.0)
            )
            project.wip_count = wip or 0
            project.avg_lead_time = avg_lt or 0.0
            project.avg_cycle_time = avg_ct or 0.0
            project.throughput_week = tp or 0.0
            project.deadline_compliance_pct = dcp or 0.0

    def _compute_access_url(self) -> None:
        super()._compute_access_url()
        for project in self:
            project.access_url = f"/my/projects/{project.id}"

    @api.depends("account_id.company_id", "partner_id.company_id")
    def _compute_company_id(self) -> None:
        for project in self:
            # if a new restriction is put on the account or the customer, the restriction on the project is updated.
            if project.account_id.company_id:
                project.company_id = project.account_id.company_id
            if not project.company_id and project.partner_id.company_id:
                project.company_id = project.partner_id.company_id

    @api.depends_context("company")
    @api.depends("company_id", "company_id.resource_calendar_id")
    def _compute_resource_calendar_id(self) -> None:
        for project in self:
            project.resource_calendar_id = (
                project.company_id.resource_calendar_id
                or self.env.company.resource_calendar_id
            )

    def _inverse_company_id(self) -> None:
        """Ensures that the new company of the project is valid for the account. If not set back the previous company, and raise a user Error.
        Ensures that the new company of the project is valid for the partner
        """
        for project in self:
            account = project.account_id
            if (
                project.partner_id
                and project.partner_id.company_id
                and project.company_id
                and project.company_id != project.partner_id.company_id
            ):
                raise UserError(
                    _(
                        "The project and the associated partner must be linked to the same company."
                    )
                )
            if not account or not account.company_id:
                continue
            # if the account of the project has more than one company linked to it, or if it has aal, do not update the account, and set back the old company on the project.
            if (
                account.project_count > 1 or account.line_ids
            ) and project.company_id != account.company_id:
                raise UserError(
                    _(
                        "The project's company cannot be changed if its analytic account has analytic lines or if more than one project is linked to it."
                    )
                )
            account.company_id = project.company_id or project.partner_id.company_id

    @api.depends("last_update_id.status")
    def _compute_last_update_status(self) -> None:
        for project in self:
            project.last_update_status = project.last_update_id.status or "to_define"

    @api.depends("last_update_status")
    def _compute_last_update_color(self) -> None:
        for project in self:
            project.last_update_color = STATUS_COLOR[project.last_update_status]

    @api.depends("milestone_ids")
    def _compute_milestone_count(self) -> None:
        read_group = self.env["project.milestone"]._read_group(
            [("project_id", "in", self.ids)], ["project_id"], ["__count"]
        )
        mapped_count = {project.id: count for project, count in read_group}
        for project in self:
            project.milestone_count = mapped_count.get(project.id, 0)

    @api.depends("milestone_ids.is_reached", "milestone_count")
    def _compute_milestone_reached_count(self) -> None:
        read_group = self.env["project.milestone"]._read_group(
            [("project_id", "in", self.ids), ("is_reached", "=", True)],
            ["project_id"],
            ["__count"],
        )
        mapped_count = {project.id: count for project, count in read_group}
        for project in self:
            project.milestone_count_reached = mapped_count.get(project.id, 0)
            project.milestone_progress = (
                project.milestone_count
                and project.milestone_count_reached * 100 // project.milestone_count
            )

    @api.depends(
        "milestone_ids",
        "milestone_ids.is_reached",
        "milestone_ids.deadline",
        "allow_milestones",
    )
    def _compute_is_milestone_exceeded(self) -> None:
        today = fields.Date.context_today(self)
        read_group = self.env["project.milestone"]._read_group(
            [
                ("project_id", "in", self.filtered("allow_milestones").ids),
                ("is_reached", "=", False),
                ("deadline", "<=", today),
            ],
            ["project_id"],
            ["__count"],
        )
        mapped_count = {project.id: count for project, count in read_group}
        for project in self:
            project.is_milestone_exceeded = bool(mapped_count.get(project.id, 0))

    @api.depends_context("company")
    @api.depends("company_id")
    def _compute_currency_id(self) -> None:
        default_currency_id = self.env.company.currency_id
        for project in self:
            project.currency_id = project.company_id.currency_id or default_currency_id

    @api.model
    def _search_is_milestone_exceeded(self, operator: str, value: Any) -> list:
        if operator != "in":
            return NotImplemented

        sql = SQL("""(
            SELECT P.id
              FROM project_project P
         LEFT JOIN project_milestone M ON P.id = M.project_id
             WHERE M.is_reached IS false
               AND P.allow_milestones IS true
               AND M.deadline <= CAST(now() AS date)
        )""")
        return [("id", "any", sql)]

    @api.depends("collaborator_ids", "privacy_visibility")
    def _compute_collaborator_count(self) -> None:
        project_sharings = self.filtered(
            lambda project: project.privacy_visibility in ["invited_users", "portal"]
        )
        collaborator_read_group = self.env["project.collaborator"]._read_group(
            [("project_id", "in", project_sharings.ids)],
            ["project_id"],
            ["__count"],
        )
        collaborator_count_by_project = {
            project.id: count for project, count in collaborator_read_group
        }
        for project in self:
            project.collaborator_count = collaborator_count_by_project.get(
                project.id, 0
            )

    @api.depends("privacy_visibility")
    def _compute_privacy_visibility_warning(self) -> None:
        for project in self:
            if not project.ids:
                project.privacy_visibility_warning = ""
            elif project.privacy_visibility in [
                "invited_users",
                "portal",
            ] and project._origin.privacy_visibility not in [
                "invited_users",
                "portal",
            ]:
                project.privacy_visibility_warning = _(
                    "Customers will be added to the followers of their project and tasks."
                )
            elif project.privacy_visibility not in [
                "invited_users",
                "portal",
            ] and project._origin.privacy_visibility in [
                "invited_users",
                "portal",
            ]:
                project.privacy_visibility_warning = _(
                    "Portal users will be removed from the followers of the project and its tasks."
                )
            else:
                project.privacy_visibility_warning = ""

    @api.depends("privacy_visibility")
    def _compute_access_instruction_message(self) -> None:
        for project in self:
            if project.privacy_visibility == "portal":
                project.access_instruction_message = self.env._(
                    "To give portal users access to your project, add them as followers. For task access, add them as followers for each task."
                )
            elif project.privacy_visibility == "followers":
                project.access_instruction_message = self.env._(
                    "Grant employees access to your project or tasks by adding them as followers. Employees automatically get access to the tasks they are assigned to."
                )
            elif project.privacy_visibility == "invited_users":
                project.access_instruction_message = self.env._(
                    "Grant users access by adding them as followers — either to the project or individual tasks. Internal users automatically gain access to tasks they are assigned to."
                )
            else:
                project.access_instruction_message = ""

    @api.depends("update_ids")
    def _compute_total_update_ids(self) -> None:
        update_count_per_project = dict(
            self.env["project.update"]._read_group(
                [("project_id", "in", self.ids)],
                ["project_id"],
                ["id:count"],
            )
        )
        for project in self:
            project.update_count = update_count_per_project.get(project, 0)

    @api.depends("workflow_step_ids.rating_active")
    def _compute_show_ratings(self) -> None:
        projects_with_rating_active = (
            self.env["project.workflow.step"]
            .search_fetch(
                domain=[
                    ("project_ids", "in", self.ids),
                    ("rating_active", "=", True),
                ],
                field_names=["project_ids"],
            )
            .project_ids
        )
        for project in self:
            project.show_ratings = project in projects_with_rating_active

    def _inverse_allow_dependencies(self) -> None:
        """Reset state for waiting tasks in the project if the feature is disabled
        or recompute the tasks with dependencies if the project has the feature enabled again
        """
        project_with_task_dependencies_feature = self.filtered("allow_dependencies")
        projects_without_task_dependencies_feature = (
            self - project_with_task_dependencies_feature
        )
        ProjectTask = self.env["project.task"]
        if project_with_task_dependencies_feature and (
            open_tasks_with_dependencies := ProjectTask.search(
                [
                    (
                        "project_id",
                        "in",
                        project_with_task_dependencies_feature.ids,
                    ),
                    ("predecessor_ids.state", "in", ProjectTask.OPEN_STATES),
                    ("state", "in", ProjectTask.OPEN_STATES),
                ]
            )
        ):
            open_tasks_with_dependencies.state = "blocked"
        if projects_without_task_dependencies_feature and (
            waiting_tasks := ProjectTask.search(
                [
                    (
                        "project_id",
                        "in",
                        projects_without_task_dependencies_feature.ids,
                    ),
                    ("state", "=", "blocked"),
                ]
            )
        ):
            waiting_tasks.state = "in_progress"
        res = self._check_project_group_with_field(
            "allow_dependencies", "project.group_project_task_dependencies"
        )
        # Hide/Show task waiting subtype when task dependencies feature is disabled/enabled
        if res or res is False:
            self.env.ref("project.mt_task_waiting").sudo().hidden = not res
            self.env.ref("project.mt_project_task_waiting").sudo().hidden = not res

    def _inverse_allow_milestones(self) -> None:
        self._check_project_group_with_field(
            "allow_milestones", "project.group_project_milestone"
        )

    def _inverse_allow_recurring_tasks(self) -> None:
        self._check_project_group_with_field(
            "allow_recurring_tasks", "project.group_project_recurring_tasks"
        )

    @api.model
    def _map_tasks_default_values(self, project: Self) -> dict:
        """Get the default value for the copied task on project duplication.
        The phase_id, name field will be set for each task in the overwritten copy_data function in project.task
        """
        return {
            "state": "in_progress",
            "company_id": project.company_id.id,
            "project_id": project.id,
        }

    def map_tasks(self, new_project_id: int) -> Self:
        """Copy and map tasks from old to new project"""
        project = self.browse(new_project_id)
        # We want to copy archived task, but do not propagate an active_test context key
        tasks = (
            self.env["project.task"]
            .with_context(active_test=False)
            .search([("project_id", "=", self.id), ("parent_id", "=", False)])
        )
        if self.allow_dependencies and "task_mapping" not in self.env.context:
            self = self.with_context(task_mapping={})
        # preserve task name and stage, normally altered during copy
        defaults = self._map_tasks_default_values(project)
        new_tasks = tasks.with_context(copy_project=True).copy(defaults)
        all_subtasks = new_tasks._get_all_subtasks()
        all_subtasks.filtered(lambda child: child.project_id == self).write(
            {"project_id": project.id}
        )
        return True

    def copy_data(self, default: dict | None = None) -> list[dict]:
        default = dict(default or {})
        vals_list = super().copy_data(default=default)
        copy_from_template = self.env.context.get("copy_from_template")
        has_project_stage_feature = False
        if copy_from_template and "phase_id" not in default:
            has_project_stage_feature = self.env.user.has_group(
                "project.group_project_stages"
            )
        for project, vals in zip(self, vals_list, strict=True):
            if project.is_template and not copy_from_template:
                vals["is_template"] = True
            if copy_from_template:
                if has_project_stage_feature:
                    vals["phase_id"] = project.phase_id.id
                for field in self._get_template_field_blacklist():
                    if field in vals and field not in default:
                        del vals[field]
            if copy_from_template or (
                not project.is_template and vals.get("is_template")
            ):
                vals["name"] = default.get("name", project.name)
            else:
                vals["name"] = default.get(
                    "name", self.env._("%s (copy)", project.name)
                )
        return vals_list

    def copy(self, default: dict | None = None) -> Self:
        default = dict(default or {})
        # Since we dont want to copy the milestones if the original project has the feature disabled, we set the milestones to False by default.
        default["milestone_ids"] = False
        copy_context = dict(
            self.env.context,
            mail_auto_subscribe_no_notify=True,
            mail_create_nosubscribe=True,
        )
        copy_context.pop("default_phase_id", None)
        new_projects = super(ProjectProject, self.with_context(copy_context)).copy(
            default=default
        )
        if "milestone_mapping" not in self.env.context:
            self = self.with_context(milestone_mapping={})
        for old_project, new_project in zip(self, new_projects, strict=True):
            for follower in old_project.message_follower_ids:
                new_project.message_subscribe(
                    partner_ids=follower.partner_id.ids,
                    subtype_ids=follower.subtype_ids.ids,
                )
            if old_project.allow_milestones:
                new_project.milestone_ids = old_project.milestone_ids.copy().ids
            if "tasks" not in default:
                old_project.map_tasks(new_project.id)
            if not old_project.active:
                new_project.with_context(active_test=False).tasks.active = True
        # Copy the shared embedded actions and config in the new projects
        shared_embedded_actions_mapping = self._copy_shared_embedded_actions(
            new_projects
        )
        self._copy_embedded_actions_config(
            new_projects, shared_embedded_actions_mapping
        )
        return new_projects

    def _copy_shared_embedded_actions(self, new_projects: Self) -> None:
        shared_embedded_actions_per_record = dict(
            self.env["ir.embedded.actions"]
            .sudo()
            ._read_group(
                domain=[
                    ("parent_res_id", "in", self.ids),
                    ("parent_res_model", "=", self._name),
                    ("user_id", "=", False),
                ],
                groupby=["parent_res_id"],
                aggregates=["id:recordset"],
            )
        )
        shared_embedded_actions_mapping = {}
        for project, new_project in zip(self, new_projects, strict=True):
            # Copy the shared embedded actions in the new record
            shared_embedded_actions = shared_embedded_actions_per_record.get(project.id)
            if shared_embedded_actions:
                copy_shared_embedded_actions = shared_embedded_actions.copy(
                    {"parent_res_id": new_project.id}
                )
                for original_action, copied_action in zip(
                    shared_embedded_actions,
                    copy_shared_embedded_actions,
                    strict=True,
                ):
                    shared_embedded_actions_mapping[original_action.id] = (
                        copied_action.id
                    )
                    copied_action.filter_ids = original_action.filter_ids.copy(
                        {"embedded_parent_res_id": new_project.id}
                    )
        return shared_embedded_actions_mapping

    def _copy_embedded_actions_config(
        self,
        new_projects: Self,
        shared_embedded_actions_mapping: dict | None = None,
    ) -> None:
        shared_embedded_actions_mapping = shared_embedded_actions_mapping or {}
        embedded_action_configs_per_project = dict(
            self.env["res.users.settings.embedded.action"]
            .sudo()
            ._read_group(
                [("res_id", "in", self.ids), ("res_model", "=", self._name)],
                ["res_id"],
                ["id:recordset"],
            )
        )
        valid_embedded_action_ids = self.env["ir.embedded.actions"].sudo().search(
            domain=[
                ("parent_res_model", "=", self._name),
                ("user_id", "=", False),
            ],
        ).ids + [False]
        new_embedded_actions_config_vals_list = []
        for project, new_project in zip(self, new_projects, strict=True):
            configs = embedded_action_configs_per_project.get(
                project.id, self.env["res.users.settings.embedded.action"]
            )
            config_vals_list = configs.copy_data({"res_id": new_project.id})
            for config_vals in config_vals_list:
                # Apply the mapping of shared embedded actions and filter the visibility and order by excluding the user-specific actions
                if config_vals["embedded_actions_visibility"]:
                    embedded_actions_visibility = [
                        shared_embedded_actions_mapping.get(action_id, action_id)
                        for action_id in [
                            False if x == "false" else int(x)
                            for x in config_vals["embedded_actions_visibility"].split(
                                ","
                            )
                        ]
                        if action_id in valid_embedded_action_ids
                    ]
                    config_vals["embedded_actions_visibility"] = ",".join(
                        "false" if action_id is False else str(action_id)
                        for action_id in embedded_actions_visibility
                    )
                if config_vals["embedded_actions_order"]:
                    embedded_actions_order = [
                        shared_embedded_actions_mapping.get(action_id, action_id)
                        for action_id in [
                            False if x == "false" else int(x)
                            for x in config_vals["embedded_actions_order"].split(",")
                        ]
                        if action_id in valid_embedded_action_ids
                    ]
                    config_vals["embedded_actions_order"] = ",".join(
                        "false" if action_id is False else str(action_id)
                        for action_id in embedded_actions_order
                    )
                new_embedded_actions_config_vals_list.append(config_vals)
        # sudo is needed to update the user settings for all users using the projects to duplicate
        self.env["res.users.settings.embedded.action"].sudo().create(
            new_embedded_actions_config_vals_list
        )

    @api.model
    def name_create(self, name: str) -> tuple[int, str]:
        res = super().name_create(name)
        if res:
            # We create a default stage `new` for projects created on the fly.
            self.browse(res[0]).workflow_step_ids += (
                self.env["project.workflow.step"].sudo().create({"name": _("New")})
            )
        return res

    @api.model_create_multi
    def create(self, vals_list: list[dict[str, Any]]) -> Self:
        # Prevent double project creation
        self = self.with_context(mail_create_nosubscribe=True)
        if any("label_tasks" in vals and not vals["label_tasks"] for vals in vals_list):
            task_label = _("Tasks")
            for vals in vals_list:
                if "label_tasks" in vals and not vals["label_tasks"]:
                    vals["label_tasks"] = task_label
        if self.env.user.has_group("project.group_project_stages"):
            if "default_phase_id" in self.env.context:
                stage = self.env["project.phase"].browse(
                    self.env.context["default_phase_id"]
                )
                # The project's company_id must be the same as the stage's company_id
                if stage.company_id:
                    for vals in vals_list:
                        if vals.get("phase_id"):
                            continue
                        vals["company_id"] = stage.company_id.id
            else:
                companies_ids = [
                    vals.get("company_id", False) for vals in vals_list
                ] + [False]
                stages = self.env["project.phase"].search(
                    [("company_id", "in", companies_ids)]
                )
                for vals in vals_list:
                    if vals.get("phase_id"):
                        continue
                    # Pick the stage with the lowest sequence with no company or project's company
                    stage_domain = (
                        [False]
                        if "company_id" not in vals
                        else [False, vals.get("company_id")]
                    )
                    stage = stages.filtered(
                        lambda s, d=stage_domain: s.company_id.id in d
                    )[:1]
                    vals["phase_id"] = stage.id

        for vals in vals_list:
            if vals.pop("is_favorite", False):
                vals["favorite_user_ids"] = [self.env.uid]
        return super().create(vals_list)

    def write(self, vals: dict[str, Any]) -> bool:
        if vals.get("access_token"):
            self.ensure_one()  # We are not supposed to add a single access token to multiple project
            if self.privacy_visibility not in ["invited_users", "portal"]:
                vals["access_token"] = ""

        # Here we modify the project's stage according to the selected company (selecting the first
        # stage in sequence that is linked to the company).
        company_id = vals.get("company_id")
        if self.env.user.has_group("project.group_project_stages") and company_id:
            projects_already_with_company = self.filtered(
                lambda p: p.company_id.id == company_id
            )
            if projects_already_with_company:
                projects_already_with_company.write(
                    {key: value for key, value in vals.items() if key != "company_id"}
                )
                self -= projects_already_with_company
            if (
                company_id not in (None, *self.company_id.ids)
                and self.phase_id.company_id
            ):
                ProjectStage = self.env["project.phase"]
                vals["phase_id"] = ProjectStage.search(
                    [("company_id", "in", (company_id, False))],
                    order=f"sequence asc, {ProjectStage._order}",
                    limit=1,
                ).id

        # directly compute is_favorite to dodge allow write access right
        if "is_favorite" in vals:
            self._set_favorite_user_ids(vals.pop("is_favorite"))

        if "last_update_status" in vals and vals["last_update_status"] != "to_define":
            for project in self:
                # This does not benefit from multi create, this is to allow the default description from being built.
                # This does seem ok since last_update_status should only be updated on one record at once.
                self.env["project.update"].with_context(
                    default_project_id=project.id
                ).create(
                    {
                        "name": _(
                            "Status Update - %(date)s",
                            date=fields.Date.today().strftime(
                                get_lang(self.env).date_format
                            ),
                        ),
                        "status": vals.get("last_update_status"),
                    }
                )
            vals.pop("last_update_status")
        if vals.get("privacy_visibility"):
            self._change_privacy_visibility(vals["privacy_visibility"])

        date_start = vals.get("date_start", True)
        date_end = vals.get("date", True)
        if not date_start or not date_end:
            vals["date_start"] = False
            vals["date"] = False
        else:
            no_current_date_begin = not all(project.date_start for project in self)
            no_current_date_end = not all(project.date for project in self)
            date_start_update = "date_start" in vals
            date_end_update = "date" in vals
            if date_start_update and no_current_date_end and not date_end_update:
                del vals["date_start"]
            elif date_end_update and no_current_date_begin and not date_start_update:
                del vals["date"]

        res = super().write(vals) if vals else True

        if "allow_dependencies" in vals and not vals.get("allow_dependencies"):
            self.env["project.task"].search(
                [
                    ("project_id", "in", self.ids),
                    ("state", "=", "blocked"),
                ]
            ).write({"state": "in_progress"})

        if "allow_recurring_tasks" in vals and not vals["allow_recurring_tasks"]:
            self.env["project.task"].search(
                [("project_id", "in", self.ids), ("recurring_task", "=", True)]
            ).write({"recurring_task": False})

        if "active" in vals:
            # archiving/unarchiving a project does it on its tasks, too
            self.with_context(active_test=False).mapped("tasks").write(
                {"active": vals["active"]}
            )
        if "name" in vals and self.account_id:
            projects_read_group = self.env["project.project"]._read_group(
                [("account_id", "in", self.account_id.ids)],
                ["account_id"],
                having=[("__count", "=", 1)],
            )
            analytic_account_to_update = self.env["account.analytic.account"].browse(
                [analytic_account.id for [analytic_account] in projects_read_group]
            )
            # Use the written value, not self.name: on a multi-record write
            # (e.g. mass rename) self.name raises "Expected singleton".
            analytic_account_to_update.write({"name": vals["name"]})
        return res

    def unlink(self) -> bool:
        # Delete the embedded action configs related to the deleted projects
        self.env["res.users.settings.embedded.action"].sudo().search(
            domain=[("res_id", "in", self.ids), ("res_model", "=", self._name)],
        ).unlink()
        # Delete the empty related analytic account
        analytic_accounts_to_delete = self.env["account.analytic.account"]
        for project in self:
            if project.account_id and not project.account_id.line_ids:
                analytic_accounts_to_delete |= project.account_id
        self.with_context(active_test=False).tasks.unlink()
        result = super().unlink()
        analytic_accounts_to_delete.unlink()
        return result

    @api.ondelete(at_uninstall=False)
    def _check_project_group_at_removal(self) -> None:
        self._check_project_group_with_field(
            "allow_dependencies", "project.group_project_task_dependencies"
        )
        self._check_project_group_with_field(
            "allow_milestones", "project.group_project_milestone"
        )
        self._check_project_group_with_field(
            "allow_recurring_tasks", "project.group_project_recurring_tasks"
        )

    def _order_field_to_sql(
        self,
        alias: str,
        field_name: str,
        direction: Any,
        nulls: Any,
        query: Any,
    ) -> SQL:
        if field_name == "is_favorite":
            sql_field = SQL(
                "%s IN (SELECT project_id FROM project_favorite_user_rel WHERE user_id = %s)",
                SQL.identifier(alias, "id"),
                self.env.uid,
            )
            return SQL("%s %s %s", sql_field, direction, nulls)

        return super()._order_field_to_sql(alias, field_name, direction, nulls, query)

    def message_subscribe(
        self,
        partner_ids: list[int] | None = None,
        subtype_ids: list[int] | None = None,
    ) -> bool:
        """Subscribe to newly created task but not all existing active task when subscribing to a project.
        User update notification preference of project its propagated to all the tasks that the user is
        currently following.
        """
        res = super().message_subscribe(
            partner_ids=partner_ids, subtype_ids=subtype_ids
        )
        if subtype_ids:
            project_subtypes = self.env["mail.message.subtype"].browse(subtype_ids)
            task_subtypes = (
                project_subtypes.mapped("parent_id")
                | project_subtypes.filtered(lambda sub: sub.internal or sub.default)
            ).ids
            if task_subtypes:
                for task in self.task_ids:
                    partners = set(task.message_partner_ids.ids) & set(partner_ids)
                    if partners:
                        task.message_subscribe(
                            partner_ids=list(partners),
                            subtype_ids=task_subtypes,
                        )
                self.update_ids.message_subscribe(
                    partner_ids=partner_ids, subtype_ids=subtype_ids
                )
        return res

    def message_unsubscribe(self, partner_ids: list[int] | None = None) -> bool:
        self.task_ids.message_unsubscribe(partner_ids=partner_ids)
        super().message_unsubscribe(partner_ids=partner_ids)
        if partner_ids:
            self.env["project.collaborator"].search(
                [
                    ("partner_id", "in", partner_ids),
                    ("project_id", "in", self.ids),
                ]
            ).unlink()

    def _alias_get_creation_values(self) -> dict:
        values = super()._alias_get_creation_values()
        values["alias_model_id"] = self.env["ir.model"]._get("project.task").id
        if self.id:
            values["alias_defaults"] = defaults = ast.literal_eval(
                self.alias_defaults or "{}"
            )
            defaults["project_id"] = self.id
        return values

    @api.constrains("phase_id")
    def _ensure_stage_has_same_company(self) -> None:
        for project in self:
            if (
                project.phase_id.company_id
                and project.phase_id.company_id != project.company_id
            ):
                raise UserError(
                    _(
                        "This project is associated with %(project_company)s, whereas the selected stage belongs to %(stage_company)s. "
                        "There are a couple of options to consider: either remove the company designation "
                        "from the project or from the stage. Alternatively, you can update the company "
                        "information for these records to align them under the same company.",
                        project_company=project.company_id.name,
                        stage_company=project.phase_id.company_id.name,
                    )
                    if project.company_id
                    else _(
                        "This project is not associated with any company, while the stage is associated with %s. "
                        "There are a couple of options to consider: either change the project's company "
                        "to align with the stage's company or remove the company designation from the stage",
                        project.phase_id.company_id.name,
                    )
                )

    @versioned_envelope
    def get_template_tasks(self) -> list:
        self.ensure_one()
        return self.env["project.task"].search_read(
            [("project_id", "=", self.id), ("is_template", "=", True)],
            ["id", "name"],
        )

    @api.model
    def _check_project_group_with_field(self, field_name: str, group_name: str) -> None:
        """Check if the user has the group 'group_name' and if there is a project with the field 'field_name' set to True.
        If not, remove the group 'group_name' from the user base group.
        Otherwise, add the group 'group_name' to the user base group.
        Returns True if the group was added, False if it was removed, None if no change was made.
        """
        has_user_group = bool(self.env.user.has_group(group_name))
        group = self.env.ref(group_name)
        base_group_user = self.env.ref("base.group_user")
        has_project_field_set = bool(
            self.env["project.project"]
            .sudo()
            .search_count([(field_name, "=", True)], limit=1)
        )
        res = None

        if not has_user_group and has_project_field_set:
            # add the group to the base user group if there is at least one project with field_name=True
            base_group_user.sudo().write({"implied_ids": [Command.link(group.id)]})
            res = True
        elif has_user_group and not has_project_field_set:
            # remove the group from the base user group if there is no project with field_name=True
            base_group_user.sudo().write({"implied_ids": [Command.unlink(group.id)]})
            group.sudo().write({"user_ids": [Command.clear()]})
            res = False
        return res

    def _get_project_features_mapping(self) -> dict:
        return {
            "allow_dependencies": "project.group_project_task_dependencies",
            "allow_milestones": "project.group_project_milestone",
            "allow_recurring_tasks": "project.group_project_recurring_tasks",
        }

    @api.model
    def check_features_enabled(self, updated_features: list[str] | None = None) -> None:
        if not self.env.user.has_group("project.group_project_user"):
            return {}
        if updated_features:
            return {
                field_name: self.env.user.has_group(group)
                for field_name, group in self._get_project_features_mapping().items()
                if field_name in updated_features
            }
        return {
            field_name: self.env.user.has_group(group)
            for field_name, group in self._get_project_features_mapping().items()
        }

    # ---------------------------------------------------
    # Mail gateway
    # ---------------------------------------------------

    def _track_template(self, changes: dict[str, Any]) -> dict:
        res = super()._track_template(changes)
        project = self[0]
        if (
            self.env.user.has_group("project.group_project_stages")
            and "phase_id" in changes
            and project.phase_id.mail_template_id
        ):
            res["phase_id"] = (
                project.phase_id.mail_template_id,
                {
                    "auto_delete_keep_log": False,
                    "subtype_id": self.env["ir.model.data"]._xmlid_to_res_id(
                        "mail.mt_note"
                    ),
                    "email_layout_xmlid": "mail.mail_notification_light",
                },
            )
        return res

    def _track_subtype(self, init_values: dict[str, Any]) -> Self:
        self.ensure_one()
        if "phase_id" in init_values:
            return self.env.ref("project.mt_project_stage_change")
        return super()._track_subtype(init_values)

    def _mail_get_message_subtypes(self) -> Self:
        res = super()._mail_get_message_subtypes()
        if len(self) == 1:
            waiting_subtype = self.env.ref("project.mt_project_task_waiting")
            if not self.allow_dependencies and waiting_subtype in res:
                res -= waiting_subtype
        return res

    def _notify_get_recipients_groups(
        self,
        message: Any,
        model_description: str,
        msg_vals: dict | bool = False,
    ) -> list:
        """Give access to the portal user/customer if the project visibility is portal."""
        groups = super()._notify_get_recipients_groups(
            message, model_description, msg_vals=msg_vals
        )
        if not self:
            return groups

        self.ensure_one()
        portal_privacy = self.privacy_visibility in ["invited_users", "portal"]
        for group_name, _group_method, group_data in groups:
            if group_name in ["portal", "portal_customer"] and not portal_privacy:
                group_data["has_button_access"] = False
        return groups

    # ---------------------------------------------------
    #  Actions
    # ---------------------------------------------------

    def action_project_task_burndown_chart_report(self) -> dict:
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "project.action_project_task_burndown_chart_report"
        )
        action["display_name"] = _("%(name)s's Burndown Chart", name=self.name)
        context = action["context"].replace("active_id", str(self.id))
        context = ast.literal_eval(context)
        context.update(
            {
                "stage_name_and_sequence_per_id": {
                    stage.id: {"sequence": stage.sequence, "name": stage.name}
                    for stage in self.workflow_step_ids
                }
            }
        )
        action["context"] = context
        return action

    def action_open_scatter_plot(self) -> dict:
        """Open cycle time scatter plot filtered to this project's tasks."""
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "project.action_project_task_scatter"
        )
        action["display_name"] = _("%(name)s's Cycle Time Scatter", name=self.name)
        return action

    def action_find_similar_projects(self) -> dict:
        """Open project history filtered to similar projects.

        Matches by overlapping tag_ids and similar team_size (±2).
        """
        self.ensure_one()
        domain = []
        if self.tag_ids:
            domain.append(("tag_ids", "in", self.tag_ids.ids))
        if self.task_count:
            # Use assignee count as proxy for team size
            team_size = len(
                self.env["project.task"]
                .search(
                    [
                        ("project_id", "=", self.id),
                        ("user_ids", "!=", False),
                    ]
                )
                .mapped("user_ids")
            )
            if team_size:
                domain.append(("team_size", ">=", max(1, team_size - 2)))
                domain.append(("team_size", "<=", team_size + 2))
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "project.action_project_history"
        )
        action["display_name"] = _("Similar Projects to %(name)s", name=self.name)
        action["domain"] = domain
        return action

    def project_update_all_action(self) -> dict:
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "project.project_update_all_action"
        )
        action["display_name"] = _("%(name)s Dashboard", name=self.name)
        return action

    def action_open_share_project_wizard(self) -> dict:
        template = self.env.ref(
            "project.mail_template_project_sharing", raise_if_not_found=False
        )

        local_context = self.env.context | {
            "default_template_id": template.id if template else False,
            "default_email_layout_xmlid": "mail.mail_notification_light",
            "active_id": self.id,
            "active_model": "project.project",
        }
        action = self.env["ir.actions.actions"]._for_xml_id(
            "project.project_share_wizard_action"
        )
        if self.env.context.get("default_access_mode"):
            action["name"] = _("Share Project")
        action["context"] = local_context
        return action

    def toggle_favorite(self) -> None:
        favorite_projects = not_fav_projects = self.env["project.project"].sudo()
        for project in self:
            if self.env.user in project.favorite_user_ids:
                favorite_projects |= project
            else:
                not_fav_projects |= project

        # Project User has no write access for project.
        not_fav_projects.write({"favorite_user_ids": [(4, self.env.uid)]})
        favorite_projects.write({"favorite_user_ids": [(3, self.env.uid)]})

    def action_view_tasks(self) -> dict:
        action = (
            self.env["ir.actions.act_window"]
            .with_context(active_id=self.id)
            ._for_xml_id("project.act_project_project_2_project_task_all")
        )
        action["display_name"] = self.name
        context = action["context"].replace("active_id", str(self.id))
        context = ast.literal_eval(context)
        context.update(
            {
                "create": self.active,
                "active_test": self.active,
                "active_id": self.id,
                "allow_milestones": self.allow_milestones,
                "allow_dependencies": self.allow_dependencies,
            }
        )
        action["context"] = context
        if self.is_template:
            action["context"].update({"template_project": True})
            action["views"] = [
                (view_id, view_type)
                for view_id, view_type in action["views"]
                if view_type not in ("pivot", "graph")
            ]
        return action

    def action_view_all_rating(self) -> dict:
        """Return the action to see all the rating of the project and activate default filters"""
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "project.rating_rating_action_view_project_rating"
        )
        action["display_name"] = _("%(name)s's Rating", name=self.name)
        action_context = (
            ast.literal_eval(action["context"]) if action["context"] else {}
        )
        action_context.update(self.env.context)
        action_context["search_default_filter_write_date"] = (
            "custom_write_date_last_30_days"
        )
        action_context.pop("group_by", None)
        action["domain"] = [
            ("consumed", "=", True),
            ("parent_res_model", "=", "project.project"),
            ("parent_res_id", "=", self.id),
        ]
        if self.rating_count == 1:
            action.update(
                {
                    "view_mode": "form",
                    "views": [
                        (view_id, view_type)
                        for view_id, view_type in action["views"]
                        if view_type == "form"
                    ],
                    "res_id": self.rating_ids[
                        0
                    ].id,  # [0] since rating_ids might be > then rating_count
                }
            )
        return dict(action, context=action_context)

    def action_view_tasks_analysis(self) -> dict:
        """Return the action to see the tasks analysis report of the project"""
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "project.action_project_task_user_tree"
        )
        action["display_name"] = _("%(name)s's Tasks Analysis", name=self.name)
        action_context = (
            ast.literal_eval(action["context"]) if action["context"] else {}
        )
        action_context["search_default_project_id"] = self.id
        return dict(action, context=action_context)

    def action_view_assigned_resources(self) -> dict:
        """Open the resource.reservation calendar restricted to this project's tasks."""
        self.ensure_one()
        # Materialize task ids: resource.reservation links to tasks via the
        # generic (res_model, res_id) reference pair, so the domain cannot
        # push the project filter down through an ORM join.
        task_ids = self.env["project.task"].search([("project_id", "=", self.id)]).ids
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "project.action_project_task_assigned_resources"
        )
        action["display_name"] = _("%(name)s's Assigned Resources", name=self.name)
        action["domain"] = [
            ("res_model", "=", "project.task"),
            ("res_id", "in", task_ids),
        ]
        return action

    def action_get_list_view(self) -> dict:
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "project.project_milestone_action"
        )
        action["display_name"] = _("%(name)s's Milestones", name=self.name)
        return action

    def action_view_tasks_from_project_milestone(self) -> dict:
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "project.project_milestone_action_view_tasks"
        )
        action["display_name"] = _("Tasks")
        action["domain"] = [("milestone_id", "in", self.milestone_ids.ids)]
        return action

    # ---------------------------------------------
    #  PROJECT UPDATES
    # ---------------------------------------------

    def action_profitability_items(
        self,
        section_name: str,
        domain: list | None = None,
        res_id: int | bool = False,
    ) -> dict:
        return {}

    def get_last_update_or_default(self) -> dict:
        self.ensure_one()
        labels = dict(
            self._fields["last_update_status"]._description_selection(self.env)
        )
        return {
            "status": labels.get(self.last_update_status, _("Set Status")),
            "color": self.last_update_color,
        }

    def get_panel_data(self) -> dict:
        self.ensure_one()
        if not self.env.user.has_group("project.group_project_user"):
            return {}
        show_profitability = self._show_profitability()
        panel_data = {
            "user": self._get_user_values(),
            "buttons": sorted(self._get_stat_buttons(), key=lambda k: k["sequence"]),
            "currency_id": self.currency_id.id,
            "show_project_profitability_helper": show_profitability
            and self._show_profitability_helper(),
            "show_milestones": self.allow_milestones,
        }
        if self.allow_milestones:
            panel_data["milestones"] = self._get_milestones()
        if show_profitability:
            profitability_items = self.with_context(
                active_test=False
            )._get_profitability_items()
            if (
                self._get_profitability_sequence_per_invoice_type()
                and profitability_items
                and "revenues" in profitability_items
                and "costs" in profitability_items
            ):  # sort the data values
                profitability_items["revenues"]["data"] = sorted(
                    profitability_items["revenues"]["data"],
                    key=lambda k: k["sequence"],
                )
                profitability_items["costs"]["data"] = sorted(
                    profitability_items["costs"]["data"],
                    key=lambda k: k["sequence"],
                )
            panel_data["profitability_items"] = profitability_items
            panel_data["profitability_labels"] = self._get_profitability_labels()
        return panel_data

    def get_milestones(self) -> list:
        if self.env.user.has_group("project.group_project_user"):
            return self._get_milestones()
        return {}

    def _get_profitability_labels(self) -> dict:
        return {}

    def _get_profitability_sequence_per_invoice_type(self) -> dict:
        return {}

    def _get_already_included_profitability_invoice_line_ids(self) -> list:
        # To be extended to avoid account.move.line overlap between
        # profitability reports.
        return []

    def _get_user_values(self) -> dict:
        return {
            "is_project_user": self.env.user.has_group("project.group_project_user"),
        }

    def _show_profitability(self) -> bool:
        self.ensure_one()
        return True

    def _show_profitability_helper(self) -> bool:
        return self.env.user.has_group("analytic.group_analytic_accounting")

    def _get_profitability_aal_domain(self) -> list:
        return [("account_id", "in", self.account_id.ids)]

    def _get_profitability_items(self, with_action: bool = True) -> dict:
        return self._get_items_from_aal(with_action)

    def _get_items_from_aal(self, with_action: bool = True) -> dict:
        return {
            "revenues": {
                "data": [],
                "total": {"invoiced": 0.0, "to_invoice": 0.0},
            },
            "costs": {"data": [], "total": {"billed": 0.0, "to_bill": 0.0}},
        }

    def _get_milestones(self) -> list:
        self.ensure_one()
        return {
            "data": self.milestone_ids._get_data_list(),
        }

    def _get_stat_buttons(self) -> list:
        self.ensure_one()
        closed_task_count = self.task_count - self.open_task_count
        if self.task_count:
            number = self.env._(
                "%(closed_task_count)s / %(task_count)s (%(closed_rate)s%%)",
                closed_task_count=closed_task_count,
                task_count=self.task_count,
                closed_rate=round(100 * closed_task_count / self.task_count),
            )
        else:
            number = self.env._(
                "%(closed_task_count)s / %(task_count)s",
                closed_task_count=closed_task_count,
                task_count=self.task_count,
            )
        buttons = [
            {
                "icon": "check",
                "text": self.label_tasks,
                "number": number,
                "action_type": "object",
                "action": "action_view_tasks",
                "show": True,
                "sequence": 1,
            }
        ]
        if self.rating_count != 0:
            if self.rating_avg >= rating_data.RATING_AVG_TOP:
                icon = "smile-o text-success"
            elif self.rating_avg >= rating_data.RATING_AVG_OK:
                icon = "meh-o text-warning"
            else:
                icon = "frown-o text-danger"
            buttons.append(
                {
                    "icon": icon,
                    "text": self.env._("Average Rating"),
                    "number": f"{int(self.rating_avg) if self.rating_avg.is_integer() else round(self.rating_avg, 1)} / 5",
                    "action_type": "object",
                    "action": "action_view_all_rating",
                    "show": self.show_ratings,
                    "sequence": 15,
                }
            )
        if self.env.user.has_group("project.group_project_user"):
            buttons.append(
                {
                    "icon": "area-chart",
                    "text": self.env._("Burndown Chart"),
                    "action_type": "action",
                    "action": "project.action_project_task_burndown_chart_report",
                    "additional_context": json.dumps(
                        {
                            "active_id": self.id,
                            "stage_name_and_sequence_per_id": {
                                stage.id: {
                                    "sequence": stage.sequence,
                                    "name": stage.name,
                                }
                                for stage in self.workflow_step_ids
                            },
                        }
                    ),
                    "show": True,
                    "sequence": 60,
                }
            )
        return buttons

    def _get_profitability_values(self) -> tuple:
        if not self.env.user.has_group("project.group_project_manager"):
            return {}, False
        profitability_items = self._get_profitability_items(False)
        if (
            profitability_items
            and "revenues" in profitability_items
            and "costs" in profitability_items
        ):  # sort the data values
            profitability_items["revenues"]["data"] = sorted(
                profitability_items["revenues"]["data"],
                key=lambda k: k["sequence"],
            )
            profitability_items["costs"]["data"] = sorted(
                profitability_items["costs"]["data"],
                key=lambda k: k["sequence"],
            )
        costs = sum(profitability_items["costs"]["total"].values())
        revenues = sum(profitability_items["revenues"]["total"].values())
        margin = revenues + costs
        to_bill_to_invoice = (
            profitability_items["costs"]["total"]["to_bill"]
            + profitability_items["revenues"]["total"]["to_invoice"]
        )
        billed_invoiced = (
            profitability_items["costs"]["total"]["billed"]
            + profitability_items["revenues"]["total"]["invoiced"]
        )
        (
            expected_percentage,
            to_bill_to_invoice_percentage,
            billed_invoiced_percentage,
        ) = (0, 0, 0)
        if revenues:
            expected_percentage = formatLang(
                self.env, (margin / revenues) * 100, digits=0
            )
        if profitability_items["revenues"]["total"]["to_invoice"]:
            to_bill_to_invoice_percentage = formatLang(
                self.env,
                (
                    to_bill_to_invoice
                    / profitability_items["revenues"]["total"]["to_invoice"]
                )
                * 100,
                digits=0,
            )
        if profitability_items["revenues"]["total"]["invoiced"]:
            billed_invoiced_percentage = formatLang(
                self.env,
                (billed_invoiced / profitability_items["revenues"]["total"]["invoiced"])
                * 100,
                digits=0,
            )
        profitability_values_dict = {
            "account_id": self.account_id,
            "costs": profitability_items["costs"],
            "revenues": profitability_items["revenues"],
            "expected_percentage": expected_percentage,
            "to_bill_to_invoice_percentage": to_bill_to_invoice_percentage,
            "billed_invoiced_percentage": billed_invoiced_percentage,
            "total": {
                "costs": costs,
                "revenues": revenues,
                "margin": margin,
                "margin_percentage": formatLang(
                    self.env,
                    (
                        not float_utils.float_is_zero(costs, precision_digits=2)
                        and (margin / -costs) * 100
                    )
                    or 0.0,
                    digits=0,
                ),
            },
            "labels": self._get_profitability_labels(),
        }
        show_profitability = bool(
            profitability_values_dict.get("account_id")
            and (
                profitability_values_dict.get("costs")
                or profitability_values_dict.get("revenues")
            )
        )
        return profitability_values_dict, show_profitability

    # ---------------------------------------------------
    #  Business Methods
    # ---------------------------------------------------

    def _get_hide_partner(self) -> bool:
        return False

    @api.model
    def _get_values_analytic_account_batch(self, project_vals_list: list[dict]) -> dict:
        project_plan, _other_plans = self.env["account.analytic.plan"]._get_all_plans()
        return [
            {
                "name": project_vals.get(
                    "name", self.env._("Unknown Analytic Account")
                ),
                "company_id": project_vals.get("company_id", False),
                "partner_id": project_vals.get("partner_id", False),
                "plan_id": project_plan.id,
            }
            for project_vals in project_vals_list
        ]

    def _create_analytic_account(self) -> None:
        analytic_accounts_values = self._get_values_analytic_account_batch(
            self._read_format(["name", "company_id", "partner_id"], None)
        )
        analytic_accounts = self.env["account.analytic.account"].create(
            analytic_accounts_values
        )
        for project, analytic_account in zip(self, analytic_accounts, strict=True):
            project.account_id = analytic_account

    def _get_projects_to_make_billable_domain(self) -> list:
        return [("partner_id", "!=", False)]

    @api.constrains(lambda self: self._get_plan_fnames())
    def _check_account_id(self) -> None:
        # Overriden from 'analytic.plan.fields.mixin'
        pass

    def _get_plan_domain(self, plan: Any) -> list:
        return Domain.AND(
            [
                super()._get_plan_domain(plan),
                [
                    "|",
                    ("company_id", "=", False),
                    ("company_id", "=?", unquote("company_id")),
                ],
            ]
        )

    def _get_account_node_context(self, plan: Any) -> dict:
        return {
            **super()._get_account_node_context(plan),
            "default_company_id": unquote("company_id"),
        }

    # ---------------------------------------------------
    # Privacy
    # ---------------------------------------------------

    def _change_privacy_visibility(self, new_visibility: str) -> None:
        """Unsubscribe non-internal users from the project and tasks if the project privacy visibility
        goes from 'portal' to a different value.
        If the privacy visibility is set to 'portal', subscribe back project and tasks partners.
        """
        for project in self:
            if project.privacy_visibility == new_visibility:
                continue
            if new_visibility in ["invited_users", "portal"]:
                project.message_subscribe(partner_ids=project.partner_id.ids)
                for task in project.task_ids.filtered("partner_id"):
                    task.message_subscribe(partner_ids=task.partner_id.ids)
            elif project.privacy_visibility in ["invited_users", "portal"]:
                portal_users = project.message_partner_ids.user_ids.filtered("share")
                project.message_unsubscribe(partner_ids=portal_users.partner_id.ids)
                project.tasks._unsubscribe_portal_users()
                # revoke access_token since the project and its tasks are no longer accessible for portal/public users
                project.tasks.access_token = ""
                project.access_token = ""

    # ---------------------------------------------------
    # Project sharing
    # ---------------------------------------------------
    def _check_project_sharing_access(self) -> None:
        self.ensure_one()
        if self.privacy_visibility not in ["invited_users", "portal"]:
            return False
        if self.env.user._is_portal():
            return self.env["project.collaborator"].search(
                [
                    ("project_id", "=", self.sudo().id),
                    ("partner_id", "=", self.env.user.partner_id.id),
                ]
            )
        return self.env.user._is_internal()

    def _add_collaborators(self, partners: Any, limited_access: bool = False) -> None:
        self.ensure_one()
        new_collaborators = self._get_new_collaborators(partners)
        if not new_collaborators:
            # Then we have nothing to do
            return
        self.write(
            {
                "collaborator_ids": [
                    Command.create(
                        {
                            "partner_id": collaborator.id,
                            "limited_access": limited_access,
                        }
                    )
                    for collaborator in new_collaborators
                ],
            }
        )

    def _get_new_collaborators(self, partners: Any) -> list:
        self.ensure_one()
        return partners.filtered(
            lambda partner: (
                partner not in self.collaborator_ids.partner_id
                and partner.partner_share
            )
        )

    def _add_followers(self, partners: Any) -> None:
        self.ensure_one()
        self.message_subscribe(partners.ids)

        dict_tasks_per_partner = {}
        dict_partner_ids_to_subscribe_per_partner = {}
        for task in self.task_ids:
            if task.partner_id in dict_tasks_per_partner:
                dict_tasks_per_partner[task.partner_id] |= task
            else:
                partner_ids_to_subscribe = [
                    partner.id
                    for partner in partners
                    if partner == task.partner_id
                    or partner in task.partner_id.child_ids
                ]
                if partner_ids_to_subscribe:
                    dict_tasks_per_partner[task.partner_id] = task
                    dict_partner_ids_to_subscribe_per_partner[task.partner_id] = (
                        partner_ids_to_subscribe
                    )
        for partner, tasks in dict_tasks_per_partner.items():
            tasks.message_subscribe(dict_partner_ids_to_subscribe_per_partner[partner])

    def _thread_to_store(
        self,
        store: Store,
        fields: list[str],
        *,
        request_list: list[str] | None = None,
    ) -> None:
        super()._thread_to_store(store, fields, request_list=request_list)
        if request_list and "followers" in request_list:
            store.add(
                self,
                {
                    "collaborator_ids": Store.Many(
                        self.sudo().collaborator_ids.partner_id, []
                    )
                },
                as_thread=True,
            )

    @api.depends("task_count", "open_task_count")
    def _compute_task_completion_percentage(self) -> None:
        for task in self:
            task.task_completion_percentage = (
                task.task_count and 1 - task.open_task_count / task.task_count
            )

    # ---------------------------------------------------
    #  Project Template Methods
    # ---------------------------------------------------

    def _get_template_to_project_warnings(self) -> list:
        self.ensure_one()
        return []

    def template_to_project_confirmation_callback(
        self, callbacks: dict[str, Any]
    ) -> dict:
        self.ensure_one()
        pass

    def _get_template_to_project_confirmation_callbacks(self) -> list:
        self.ensure_one()
        return {}

    def action_toggle_project_template_mode(self) -> dict | bool:
        self.ensure_one()
        config = {
            "params": {
                "project_id": self.id,
            },
        }
        if self.is_template:
            config["tag"] = "project_template_show_undo_confirmation_dialog"
            if callbacks := self._get_template_to_project_confirmation_callbacks():
                config["params"]["callback_data"] = {
                    "method": "template_to_project_confirmation_callback",
                    "args": [self.id, callbacks],
                }
            if warning_messages := self._get_template_to_project_warnings():
                config["params"]["message"] = self.env._(
                    "%(warning_messages)s\nAre you sure you want to continue?",
                    warning_messages="\n".join(warning_messages),
                )
            else:
                config["params"]["message"] = self.env._(
                    "This project is currently a template. Would you like to convert it back into a regular project?",
                )
        else:
            config["tag"] = "project_to_template_redirection_action"
        return {
            "type": "ir.actions.client",
            **config,
        }

    def create_template_from_project_undo_callback(
        self, callbacks: dict[str, Any]
    ) -> dict:
        self.ensure_one()
        if callbacks.get("unarchive_project"):
            self.action_unarchive()

    def _get_template_from_project_undo_callbacks(self) -> list:
        self.ensure_one()
        callbacks = {}
        if self.active:
            self.action_archive()
            callbacks["unarchive_project"] = True
        return callbacks

    def action_create_template_from_project(self) -> dict:
        self.ensure_one()
        template = self.copy(default={"is_template": True, "partner_id": False})
        template._toggle_template_mode(True)
        template.message_post(body=self.env._("Template created from %s.", self.name))
        config = {
            "tag": "project_template_show_notification",
            "params": {
                "project_id": template.id,
                "undo_method": "unlink",
            },
        }
        if callbacks := self._get_template_from_project_undo_callbacks():
            config["params"]["callback_data"] = {
                "method": "create_template_from_project_undo_callback",
                "args": [self.id, callbacks],
                "post_action": {
                    "type": "ir.actions.client",
                    "tag": "display_notification",
                    "params": {
                        "type": "success",
                        "message": self.env._(
                            "Template converted back to regular project."
                        ),
                    },
                },
            }
        return {
            "type": "ir.actions.client",
            **config,
        }

    def action_undo_convert_to_template(self) -> dict | bool:
        self.ensure_one()
        self._toggle_template_mode(False)
        self.message_post(
            body=self.env._("Template converted back to regular project.")
        )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "message": self.env._("Template converted back to regular project."),
                "next": {
                    "type": "ir.actions.client",
                    "tag": "soft_reload",
                },
            },
        }

    def _toggle_template_mode(self, is_template: bool) -> None:
        self.ensure_one()
        self.is_template = is_template
        if not is_template:
            self.task_ids.role_ids = False

    @api.model
    def _get_template_default_context_whitelist(self) -> set[str]:
        """Whitelist of fields that can be set through the `default_` context keys when creating a project from a template."""
        return [
            "allow_milestones",
        ]

    @api.model
    def _get_template_field_blacklist(self) -> set[str]:
        """Blacklist of fields to not copy when creating a project from a template."""
        return [
            "partner_id",
        ]

    def action_create_from_template(
        self, values: dict | None = None, role_to_users_mapping: Any = None
    ) -> Self:
        self.ensure_one()
        values = values or {}

        if self.date_start and self.date:
            if not values.get("date_start"):
                values["date_start"] = fields.Date.today()
            if not values.get("date"):
                values["date"] = values["date_start"] + (self.date - self.date_start)

        default = {
            key.removeprefix("default_"): value
            for key, value in self.env.context.items()
            if key.startswith("default_")
            and key.removeprefix("default_")
            in self._get_template_default_context_whitelist()
        } | values
        project = self.with_context(
            copy_from_template=True, copy_from_project_template=True
        ).copy(default=default)
        project.message_post(
            body=self.env._("Project created from template %(name)s.", name=self.name)
        )

        # Tasks dispatching using project roles
        if role_to_users_mapping and (
            mapping := role_to_users_mapping.filtered(lambda entry: entry.user_ids)
        ):
            for new_task in project.task_ids:
                for entry in mapping:
                    if entry.role_id in new_task.role_ids:
                        new_task.user_ids |= entry.user_ids

        project.task_ids.role_ids = False
        return project

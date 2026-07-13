import logging
import re
from collections import defaultdict
from datetime import datetime, time, timedelta
from typing import Any, Self

from lxml import html
from pytz import UTC

from odoo import SUPERUSER_ID, _, api, fields, models, tools
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Command, Date, Domain
from odoo.tools import (
    SQL,
    LazyTranslate,
    float_compare,
    float_is_zero,
    format_list,
    html_sanitize,
)

from odoo.addons.html_editor.tools import handle_history_divergence
from odoo.addons.mail.tools.discuss import Store
from odoo.addons.project.controllers.project_sharing_chatter import (
    ProjectSharingChatter,
)
from odoo.addons.rating.models import rating_data
from odoo.addons.resource.models.utils import filter_domain_leaf

_logger = logging.getLogger(__name__)
_lt = LazyTranslate(__name__)

PROJECT_TASK_READABLE_FIELDS = {
    "id",
    "active",
    "priority",
    "project_id",
    "display_in_project",
    "allow_dependencies",
    "subtask_count",
    "email_from",
    "create_date",
    "write_date",
    "company_id",
    "displayed_image_id",
    "display_name",
    "portal_user_names",
    "user_ids",
    "display_parent_task_button",
    "current_user_same_company_partner",
    "allow_recurring_tasks",
    "allow_milestones",
    "milestone_id",
    "has_late_and_unreached_milestone",
    "date_assign",
    "successor_ids",
    "message_is_follower",
    "recurring_task",
    "closed_subtask_count",
    "successor_count",
    "predecessor_ids",
    "predecessor_count",
    "repeat_interval",
    "repeat_unit",
    "repeat_type",
    "repeat_until",
    "recurrence_id",
    "recurring_count",
    "duration_tracking",
    "display_follow_button",
    "is_template",
    "has_template_ancestor",
    "has_project_template",
    "step_color",
    "deadline_met",
    "cd3_score",
    "access_token",
    "access_url",
}

PROJECT_TASK_WRITABLE_FIELDS = {
    "name",
    "description",
    "partner_id",
    "planned_date_begin",
    "date_end",
    "date_last_status_change",
    "tag_ids",
    "sequence",
    "step_id",
    "child_ids",
    "color",
    "parent_id",
    "priority",
    "state",
    "is_closed",
}

CLOSED_STATES = {
    "done": "Done",
    "canceled": "Cancelled",
}


class ProjectTask(models.Model):
    _name = "project.task"
    _description = "Task"
    _date_name = "date_assign"
    _inherit = [
        "html.field.history.mixin",
        "mail.thread.cc",
        "mail.activity.mixin",
        "mail.tracking.duration.mixin",
        "portal.mixin",
        "rating.mixin",
        "resource.scheduling.mixin",
    ]
    _mail_post_access = "read"
    _mail_thread_customer = True
    _order = "priority desc, sequence, date_end asc, id desc"
    _primary_email = "email_from"
    _systray_view = "list"
    _track_duration_field = "step_id"

    def _get_versioned_fields(self) -> list[str]:
        return [ProjectTask.description.name]

    @api.model
    def _get_default_partner_id(self, project=None, parent=None) -> int | bool:
        if parent and parent.partner_id:
            return parent.partner_id.id
        if project and project.partner_id:
            return project.partner_id.id
        return False

    def _get_default_step_id(self) -> int | bool:
        """Gives default step_id"""
        project_id = self.env.context.get("default_project_id")
        if not project_id:
            return False
        return self.step_find(project_id, order="fold, sequence, id")

    @api.model
    def _default_user_ids(self) -> tuple | list[int]:
        return (
            self.env.user.ids
            if any(
                key in self.env.context
                for key in (
                    "default_triage_ids",
                    "default_triage_id",
                )
            )
            else ()
        )

    @api.model
    def _default_company_id(self) -> bool:
        if self.env.context.get("default_project_id"):
            return (
                self.env["project.project"]
                .browse(self.env.context["default_project_id"])
                .company_id
            )
        return False

    @api.model
    def _read_group_step_ids(self, stages: Self, domain: list) -> Self:
        search_domain = [("id", "in", stages.ids)]
        if (
            "default_project_id" in self.env.context
            and not self.env.context.get("subtask_action")
            and "project_kanban" in self.env.context
        ):
            search_domain = [
                "|",
                ("project_ids", "=", self.env.context["default_project_id"]),
            ] + search_domain

        step_ids = stages._search(search_domain, order=stages._order)
        return stages.browse(step_ids)

    @api.model
    def _read_group_triage_ids(self, stages: Self, domain: list) -> Self:
        return stages.search(
            ["|", ("id", "in", stages.ids), ("user_id", "=", self.env.user.id)]
        )

    project_id = fields.Many2one(
        "project.project",
        string="Project",
        domain="['|', ('company_id', '=', False), ('company_id', '=?',  company_id)]",
        compute="_compute_project_id",
        store=True,
        precompute=True,
        recursive=True,
        readonly=False,
        index=True,
        tracking=True,
        change_default=True,
        falsy_value_label=_lt("🔒 Private"),
    )
    project_privacy_visibility = fields.Selection(
        related="project_id.privacy_visibility",
        string="Project Visibility",
        tracking=False,
    )
    display_in_project = fields.Boolean(
        compute="_compute_display_in_project",
        store=True,
        export_string_translation=False,
    )
    task_properties = fields.Properties(
        "Properties",
        definition="project_id.task_properties_definition",
        copy=True,
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        compute="_compute_company_id",
        store=True,
        readonly=False,
        recursive=True,
        copy=True,
        default=_default_company_id,
    )
    partner_id = fields.Many2one(
        "res.partner",
        string="Customer",
        recursive=True,
        tracking=True,
        compute="_compute_partner_id",
        store=True,
        readonly=False,
        index="btree_not_null",
        domain="['|', ('company_id', '=?', company_id), ('company_id', '=', False)]",
    )
    partner_phone = fields.Char(
        compute="_compute_partner_phone",
        inverse="_inverse_partner_phone",
        string="Contact Number",
        readonly=False,
        store=True,
        copy=False,
    )
    name = fields.Char(
        string="Title",
        tracking=True,
        required=True,
        index="trigram",
    )
    active = fields.Boolean(default=True, export_string_translation=False)
    sequence = fields.Integer(
        string="Sequence", default=10, export_string_translation=False
    )
    description = fields.Html(string="Description", sanitize_attributes=False)
    color = fields.Integer(
        string="Color Index",
        export_string_translation=False,
    )
    create_date = fields.Datetime("Created On", readonly=True, index=True)
    write_date = fields.Datetime("Last Updated On", readonly=True)
    date_closed = fields.Datetime(string="Closed Date", index=True, copy=False)
    date_assign = fields.Datetime(
        string="Assigning Date",
        copy=False,
        readonly=True,
        help="Date on which this task was last assigned (or unassigned). Based on this, you can get statistics on the time it usually takes to assign tasks.",
    )
    # Scheduled time range — PMI Constraint Start Date / Constraint End Date.
    # User-entered values (independent of CPM-calculated planned_date_start /
    # planned_date_end above).  ``date_end`` doubles as the deadline label
    # for backward compatibility with vanilla Odoo's project module.
    planned_date_begin = fields.Datetime(
        "Start date",
        tracking=True,
        copy=False,
    )
    date_end = fields.Datetime(
        string="Deadline",
        index=True,
        tracking=True,
        copy=False,
    )
    _planned_dates_check = models.Constraint(
        "CHECK ((planned_date_begin <= date_end))",
        "The planned start date must be before the planned end date.",
    )

    priority = fields.Selection(
        [
            ("0", "Normal"),
            ("1", "Important"),
            ("2", "High"),
            ("3", "Urgent"),
        ],
        default="0",
        index=True,
        string="Priority",
        tracking=True,
    )
    state = fields.Selection(
        [
            ("todo", "To Do"),
            ("in_progress", "In Progress"),
            ("changes_requested", "Changes Requested"),
            ("approved", "Approved"),
            *CLOSED_STATES.items(),
            ("blocked", "Waiting"),
        ],
        string="State",
        copy=False,
        default="todo",
        required=True,
        compute="_compute_state",
        inverse="_inverse_state",
        readonly=False,
        store=True,
        index=True,
        recursive=True,
        tracking=True,
    )
    is_closed = fields.Boolean(
        "Closed state",
        compute="_compute_is_closed",
        search="_search_is_closed",
    )

    step_id = fields.Many2one(
        "project.workflow.step",
        string="Workflow Step",
        compute="_compute_step_id",
        store=True,
        readonly=False,
        ondelete="restrict",
        tracking=True,
        index=True,
        default=_get_default_step_id,
        group_expand="_read_group_step_ids",
        domain="[('project_ids', '=', project_id)]",
    )
    step_color = fields.Integer(
        related="step_id.color",
        string="Step Color",
        export_string_translation=False,
    )
    rating_active = fields.Boolean(
        related="step_id.rating_active",
        string="Step Rating Status",
    )
    date_last_status_change = fields.Datetime(
        string="Last Status Change",
        index=True,
        copy=False,
        readonly=True,
        help="Date on which the state of your task has last been modified.\n"
        "Based on this information you can identify tasks that are stalling and get statistics on the time it usually takes to move tasks from one stage/state to another.",
    )

    role_ids = fields.Many2many(
        "project.role",
        string="Project Roles",
        help="When you create a project from a template, you can choose which employee takes each role. These employees will be added to the tasks, along with anyone already assigned.",
    )
    # Tracking of this field is done in the write function
    user_ids = fields.Many2many(
        "res.users",
        relation="project_task_user_rel",
        column1="task_id",
        column2="user_id",
        string="Assignees",
        context={"active_test": False},
        tracking=True,
        default=_default_user_ids,
        domain="[('share', '=', False), ('active', '=', True)]",
        falsy_value_label=_lt("👤 Unassigned"),
    )
    tag_ids = fields.Many2many("project.tags", string="Tags")

    # PMI hours model: scheduled (duration) -> planned (effort) ->
    # allocated (commitment). See reference/business/pmi-hours-model.md.
    scheduled_hours = fields.Float(
        "Working Duration",
        compute="_compute_scheduled_hours",
        store=True,
        help="Working hours within the task's date range, computed against "
        "the company calendar.  PMBOK: Activity Duration in working time "
        "units.  One person at 100%% allocation could cover this many hours.",
    )
    planned_resources = fields.Integer(
        "Planned Resources",
        default=1,
        tracking=True,
        help="Number of parallel resources the PM expects to need to deliver "
        "this task in its scheduled window.  Multiplies scheduled_hours to "
        "derive total effort (planned_hours).  Example: 2-day window (16h) "
        "with planned_resources=2 -> 32h effort = work for two people in "
        "parallel.  PMBOK: planned resource units.",
    )
    _planned_resources_positive = models.Constraint(
        "CHECK (planned_resources > 0)",
        "Planned Resources must be greater than zero.",
    )
    planned_hours = fields.Float(
        "Planned Hours",
        compute="_compute_planned_hours",
        inverse="_inverse_planned_hours",
        store=True,
        readonly=False,
        help="Estimated person-hours to complete the task.  Auto-derived as "
        "scheduled_hours x planned_resources x (allocated_percentage / 100); "
        "user can override.  PMBOK: Activity Effort / Work (scope baseline).",
    )
    allocated_hours = fields.Float(
        "Allocated Hours",
        tracking=True,
        help="Working hours committed across all assigned employees "
        "(sum of reservation_ids.allocated_hours).  PMBOK: Resource "
        "Assignment Work / total person-hours.",
    )
    allocation_state = fields.Selection(
        [
            ("unestimated", "Unestimated"),
            ("unallocated", "Unallocated"),
            ("under_allocated", "Under-Allocated"),
            ("allocated", "Allocated"),
            ("over_allocated", "Over-Allocated"),
        ],
        string="Allocation Status",
        compute="_compute_allocation_state",
        store=True,
        help="Resource allocation health relative to plan.  Tracks whether "
        "the task has enough employees committed to cover its planned "
        "effort.  Operational signal for PMs.  Pattern analog to "
        "invoice_state on sale.order.",
    )
    # allocated_percentage inherited from resource.scheduling.mixin —
    # uniform fractional allocation passed through to every reservation
    # via _get_reservation_vals_list.  Per-resource fractional units (PMI
    # strict per-assignment Units) lives on resource.reservation.
    subtask_planned_hours = fields.Float(
        "Sub-tasks Planned Hours",
        compute="_compute_subtask_planned_hours",
        export_string_translation=False,
        help="Sum of the planned hours for all the sub-tasks (and their own sub-tasks) linked to this task. Usually less than or equal to the planned hours of this task.",
    )
    # User names displayed in project sharing views
    portal_user_names = fields.Char(
        compute="_compute_portal_user_names",
        compute_sudo=True,
        search="_search_portal_user_names",
        export_string_translation=False,
    )
    # Per-user triage bucket assignment — see project_task_triage.py
    triage_ids = fields.Many2many(
        "project.triage",
        "project_task_triage",
        column1="task_id",
        column2="triage_id",
        ondelete="restrict",
        group_expand="_read_group_triage_ids",
        copy=False,
        domain="[('user_id', '=', uid)]",
        string="Personal Triage Buckets",
        export_string_translation=False,
    )
    # Personal Stage computed from the user
    personal_triage_id = fields.Many2one(
        "project.task.triage",
        string="Personal Stage State",
        compute_sudo=False,
        compute="_compute_personal_triage_id",
        search="_search_personal_triage_id",
        group_expand="_read_group_triage_ids",
        help="The current user's personal stage.",
    )
    triage_id = fields.Many2one(
        "project.triage",
        string="Personal Triage",
        related="personal_triage_id.triage_id",
        readonly=False,
        store=False,
        help="The current user's personal triage bucket.",
        domain="[('user_id', '=', uid)]",
        group_expand="_read_group_triage_ids",
    )
    # Need this field to check there is no email loops when Odoo reply automatically
    email_from = fields.Char("Email From")
    email_cc = fields.Char(
        help="Email addresses that were in the CC of the incoming emails from this task and that are not currently linked to an existing customer."
    )

    attachment_ids = fields.One2many(
        "ir.attachment",
        compute="_compute_attachment_ids",
        string="Attachments",
        export_string_translation=False,
        help="Attachments that don't come from a message",
    )
    # In the domain of displayed_image_id, we couln't use attachment_ids because a one2many is represented as a list of commands so we used res_model & res_id
    displayed_image_id = fields.Many2one(
        "ir.attachment",
        domain="[('res_model', '=', 'project.task'), ('res_id', '=', id), ('mimetype', 'ilike', 'image')]",
        string="Cover Image",
    )

    # Task Dependencies fields
    allow_dependencies = fields.Boolean(
        related="project_id.allow_dependencies",
        export_string_translation=False,
    )
    parent_id = fields.Many2one(
        "project.task",
        string="Parent Task",
        inverse="_inverse_parent_id",
        index=True,
        domain="['!', ('id', 'child_of', id)]",
        tracking=True,
    )
    child_ids = fields.One2many(
        "project.task",
        "parent_id",
        string="Sub-tasks",
        domain="[('recurring_task', '=', False)]",
        export_string_translation=False,
    )
    subtask_count = fields.Integer(
        "Sub-task Count",
        compute="_compute_subtask_count",
        export_string_translation=False,
    )
    closed_subtask_count = fields.Integer(
        "Closed Sub-tasks Count",
        compute="_compute_subtask_count",
        export_string_translation=False,
    )
    subtask_completion_percentage = fields.Float(
        compute="_compute_subtask_completion_percentage",
        export_string_translation=False,
    )
    # Tracking of this field is done in the write function
    predecessor_ids = fields.Many2many(
        "project.task",
        relation="project_task_dependency_rel",
        column1="task_id",
        column2="depends_on_id",
        string="Blocked By",
        tracking=True,
        copy=False,
        domain="[('project_id', '!=', False), ('id', '!=', id)]",
    )
    predecessor_count = fields.Integer(
        string="Depending on Tasks",
        compute="_compute_predecessor_count",
        compute_sudo=True,
    )
    closed_predecessor_count = fields.Integer(
        string="Closed Depending on Tasks",
        compute="_compute_predecessor_count",
        compute_sudo=True,
    )
    successor_ids = fields.Many2many(
        "project.task",
        relation="project_task_dependency_rel",
        column1="depends_on_id",
        column2="task_id",
        string="Block",
        copy=False,
        domain="[('project_id', '!=', False), ('id', '!=', id)]",
        export_string_translation=False,
    )
    successor_count = fields.Integer(
        string="Dependent Tasks",
        compute="_compute_successor_count",
        export_string_translation=False,
    )
    # Typed dependencies (FS/SS/FF/SF) — enriches the M2M above
    dependency_ids = fields.One2many(
        "project.task.dependency",
        "task_id",
        string="Dependency Details",
        help="Typed dependencies with FS/SS/FF/SF and lag.",
        export_string_translation=False,
    )
    dependent_on_me_ids = fields.One2many(
        "project.task.dependency",
        "depends_on_id",
        string="Tasks Depending on Me",
        export_string_translation=False,
    )

    # Critical path fields — computed on demand via project action
    earliest_start = fields.Datetime(
        "Earliest Start",
        copy=False,
        help="Computed by critical path analysis (forward pass).",
        export_string_translation=False,
    )
    latest_start = fields.Datetime(
        "Latest Start",
        copy=False,
        help="Computed by critical path analysis (backward pass).",
        export_string_translation=False,
    )
    total_float = fields.Float(
        "Total Float (hours)",
        copy=False,
        help="Latest Start - Earliest Start. Zero = critical path.",
        export_string_translation=False,
    )
    is_critical_path = fields.Boolean(
        "On Critical Path",
        copy=False,
        help="True when total_float is zero (no scheduling slack).",
        export_string_translation=False,
    )
    planned_date_start = fields.Datetime(
        "Planned Start",
        copy=False,
        help="Calendar-aware start date computed by CPM. Distinct from date_end (user-entered).",
        export_string_translation=False,
    )
    planned_date_end = fields.Datetime(
        "Planned End",
        copy=False,
        help="Calendar-aware end date computed by CPM. Distinct from date_closed (actual completion).",
        export_string_translation=False,
    )

    # Resource overallocation warning
    is_overallocated = fields.Boolean(
        "Overallocated Assignee",
        compute="_compute_is_overallocated",
        help=(
            "True when any of this task's reservations conflicts in time "
            "with another reservation of the same resource summing more "
            "than 100% allocation (PMBOK concurrent overcommit)."
        ),
        export_string_translation=False,
    )

    # ── Elapsed time metrics (calendar-adjusted) ──────────────────
    # Queue time: create → assign (how long before someone picks it up)
    queue_time_hours = fields.Float(
        "Queue Time (hours)",
        compute="_compute_elapsed",
        digits=(16, 2),
        store=True,
        aggregator="avg",
        help="Working hours from task creation to first assignment.",
    )
    queue_time_days = fields.Float(
        "Queue Time (days)",
        compute="_compute_elapsed",
        store=True,
        aggregator="avg",
        help="Working days from task creation to first assignment.",
    )
    # Lead time: create → end (total request-to-delivery)
    lead_time_hours = fields.Float(
        "Lead Time (hours)",
        compute="_compute_elapsed",
        digits=(16, 2),
        store=True,
        aggregator="avg",
        help="Working hours from task creation to closure. Includes queue wait.",
    )
    lead_time_days = fields.Float(
        "Lead Time (days)",
        compute="_compute_elapsed",
        store=True,
        aggregator="avg",
        help="Working days from task creation to closure. Includes queue wait.",
    )
    # Cycle time: assign → end (active work only, excludes queue)
    cycle_time_hours = fields.Float(
        "Cycle Time (hours)",
        compute="_compute_elapsed",
        digits=(16, 2),
        store=True,
        aggregator="avg",
        help="Working hours from first assignment to closure. Excludes queue wait.",
    )
    cycle_time_days = fields.Float(
        "Cycle Time (days)",
        compute="_compute_elapsed",
        store=True,
        aggregator="avg",
        help="Working days from first assignment to closure. Excludes queue wait.",
    )

    # Deadline compliance — foundation for estimation improvement
    deadline_met = fields.Selection(
        [("met", "Met"), ("missed", "Missed")],
        "Deadline Result",
        compute="_compute_deadline_met",
        store=True,
        help=(
            "Whether this task was closed on or before its deadline. "
            "Empty when the task has no deadline or is not yet closed — a "
            "distinct case from 'missed', which a Boolean could not represent."
        ),
        export_string_translation=False,
    )

    # Economic prioritization — Reinertsen: cost of delay / duration
    cost_of_delay = fields.Float(
        "Cost of Delay",
        tracking=True,
        help=(
            "Estimated weekly cost of not completing this task (in currency). "
            "Used to compute CD3 score for value-based prioritization."
        ),
    )
    cd3_score = fields.Float(
        "CD3 Score",
        compute="_compute_cd3_score",
        store=True,
        help=(
            "Cost of Delay Divided by Duration (CD3). Higher = do first. "
            "Computed as cost_of_delay / planned_hours when both are set."
        ),
        export_string_translation=False,
    )

    # Sprint fields — feature-flagged via use_sprints on project
    sprint_id = fields.Many2one(
        "project.sprint",
        string="Sprint",
        index="btree_not_null",
        domain="[('project_id', '=', project_id)]",
        tracking=True,
        copy=False,
    )
    use_sprints = fields.Boolean(
        related="project_id.use_sprints",
        export_string_translation=False,
    )
    story_points = fields.Float(
        "Story Points",
        help="Relative effort estimate. Used for sprint velocity tracking.",
    )

    # recurrence fields
    allow_recurring_tasks = fields.Boolean(
        related="project_id.allow_recurring_tasks",
        export_string_translation=False,
    )
    recurring_task = fields.Boolean(string="Recurrent")
    recurring_count = fields.Integer(
        string="Tasks in Recurrence",
        compute="_compute_recurring_count",
    )
    recurrence_id = fields.Many2one(
        "project.task.recurrence",
        copy=False,
        index="btree_not_null",
    )
    repeat_interval = fields.Integer(
        string="Repeat Every",
        default=1,
        compute="_compute_repeat",
        compute_sudo=True,
        readonly=False,
    )
    repeat_unit = fields.Selection(
        [
            ("day", "Days"),
            ("week", "Weeks"),
            ("month", "Months"),
            ("year", "Years"),
        ],
        default="week",
        compute="_compute_repeat",
        compute_sudo=True,
        readonly=False,
    )
    repeat_type = fields.Selection(
        [
            ("forever", "Forever"),
            ("until", "Until"),
        ],
        default="forever",
        string="Until",
        compute="_compute_repeat",
        compute_sudo=True,
        readonly=False,
    )
    repeat_until = fields.Date(
        string="End Date",
        compute="_compute_repeat",
        compute_sudo=True,
        readonly=False,
    )

    allow_milestones = fields.Boolean(
        related="project_id.allow_milestones",
        export_string_translation=False,
    )
    milestone_id = fields.Many2one(
        "project.milestone",
        "Milestone",
        domain="[('project_id', '=', project_id)]",
        compute="_compute_milestone_id",
        readonly=False,
        store=True,
        tracking=True,
        index="btree_not_null",
        help="Deliver your services automatically when a milestone is reached by linking it to a sales order item.",
    )
    has_late_and_unreached_milestone = fields.Boolean(
        compute="_compute_has_late_and_unreached_milestone",
        search="_search_has_late_and_unreached_milestone",
        export_string_translation=False,
    )

    # customer portal: include comment and (incoming/outgoing) emails in communication history
    website_message_ids = fields.One2many(
        domain=lambda self: [
            ("model", "=", self._name),
            (
                "message_type",
                "in",
                ["email", "comment", "email_outgoing", "auto_comment"],
            ),
        ],
        export_string_translation=False,
    )

    is_template = fields.Boolean(export_string_translation=False)
    has_project_template = fields.Boolean(
        related="project_id.is_template",
        string="Has Project Template",
        export_string_translation=False,
    )
    has_template_ancestor = fields.Boolean(
        compute="_compute_has_template_ancestor",
        search="_search_has_template_ancestor",
        recursive=True,
        export_string_translation=False,
        store=True,
    )

    # Project sharing fields
    display_parent_task_button = fields.Boolean(
        compute="_compute_display_parent_task_button",
        compute_sudo=True,
        export_string_translation=False,
    )
    current_user_same_company_partner = fields.Boolean(
        compute="_compute_current_user_same_company_partner",
        compute_sudo=True,
        export_string_translation=False,
    )
    display_follow_button = fields.Boolean(
        compute="_compute_display_follow_button",
        compute_sudo=True,
        export_string_translation=False,
    )

    # Quick creation shortcuts
    display_name = fields.Char(
        inverse="_inverse_display_name",
        help="""Use these keywords in the title to set new tasks:\n
            #tags Set tags on the task
            @user Assign the task to a user
            ! Set the task a medium priority
            !! Set the task a high priority
            !!! Set the task a urgent priority\n
            Make sure to use the right format and order e.g. Improve the configuration screen #feature #v16 @Mitchell !""",
    )
    link_preview_name = fields.Char(
        compute="_compute_link_preview_name",
        export_string_translation=False,
    )

    _recurring_task_has_no_parent = models.Constraint(
        "CHECK (NOT (recurring_task IS TRUE AND parent_id IS NOT NULL))",
        "You cannot convert this task into a sub-task because it is recurrent.",
    )
    _private_task_has_no_parent = models.Constraint(
        "CHECK (NOT (project_id IS NULL AND parent_id IS NOT NULL))",
        "A private task cannot have a parent.",
    )

    _is_template_idx = models.Index("(is_template) WHERE is_template IS TRUE")

    @api.constrains("company_id", "partner_id")
    def _ensure_company_consistency_with_partner(self) -> None:
        """Ensures that the company of the task is valid for the partner."""
        for task in self:
            if (
                task.partner_id
                and task.partner_id.company_id
                and task.company_id
                and task.company_id != task.partner_id.company_id
            ):
                raise ValidationError(
                    _(
                        "The task and the associated partner must be linked to the same company."
                    )
                )

    @api.constrains("child_ids", "project_id")
    def _ensure_super_task_is_not_private(self) -> None:
        """Ensures that the company of the task is valid for the partner."""
        for task in self:
            if not task.project_id and task.subtask_count:
                raise ValidationError(
                    _("This task has sub-tasks, so it can't be private.")
                )

    @property
    def TASK_PORTAL_READABLE_FIELDS(self) -> set[str]:
        return PROJECT_TASK_READABLE_FIELDS

    @property
    def TASK_PORTAL_WRITABLE_FIELDS(self) -> set[str]:
        return PROJECT_TASK_WRITABLE_FIELDS

    @api.depends("parent_id.project_id")
    def _compute_project_id(self) -> None:
        self.env.remove_to_compute(self._fields["display_in_project"], self)
        for task in self:
            if (
                not task.display_in_project
                and task.parent_id
                and task.parent_id.project_id != task.project_id
            ):
                task.project_id = task.parent_id.project_id

    @api.depends("project_id", "parent_id")
    def _compute_display_in_project(self) -> None:
        for record in self:
            record.display_in_project = not record.project_id or (
                not record.parent_id or record.project_id != record.parent_id.project_id
            )

    def _inverse_parent_id(self) -> None:
        for task in self.sudo():
            if not task.parent_id:
                task.display_in_project = True
            elif (
                task.display_in_project
                and task.project_id == task.parent_id.sudo().project_id
            ):
                task.display_in_project = False

    @api.depends("step_id", "predecessor_ids.state")
    def _compute_state(self) -> None:
        for task in self:
            dependent_open_tasks = []
            if task.allow_dependencies:
                dependent_open_tasks = [
                    dependent_task
                    for dependent_task in task.predecessor_ids
                    if dependent_task.state not in CLOSED_STATES
                ]
            # if one of the blocking task is in a blocking state
            if dependent_open_tasks:
                # here we check that the blocked task is not already in a closed state (if the task is already done we don't put it in waiting state)
                if task.state not in CLOSED_STATES:
                    task.state = "blocked"
            # if the task as no blocking dependencies and is in waiting_normal, the task goes back to in progress
            elif task.state not in CLOSED_STATES:
                task.state = "in_progress"

    @api.depends("state")
    def _compute_is_closed(self) -> None:
        for task in self:
            task.is_closed = task.state in CLOSED_STATES

    def _search_is_closed(self, operator: str, value: Any) -> list:
        if operator == "in":
            searched_states = list(CLOSED_STATES.keys())
        elif operator == "not in":
            searched_states = self.OPEN_STATES
        else:
            return NotImplemented
        return [("state", "in", searched_states)]

    def _is_rotting_feature_enabled(self):
        """Override: project.task uses date_last_status_change instead of date_last_stage_update."""
        return (
            "rotting_threshold_days" in self[self._track_duration_field]
            and "date_last_status_change" in self
            and (
                not self
                or any(
                    stage.rotting_threshold_days
                    for stage in self[self._track_duration_field]
                )
            )
        )

    def _get_rotting_depends_fields(self) -> list[str]:
        """Override: use date_last_status_change instead of date_last_stage_update."""
        if (
            hasattr(self, "_track_duration_field")
            and "rotting_threshold_days" in self[self._track_duration_field]
        ):
            return [
                "date_last_status_change",
                f"{self._track_duration_field}.rotting_threshold_days",
                "is_closed",
            ]
        return ["is_closed"]

    def _compute_rotting(self):
        """Override: use date_last_status_change instead of date_last_stage_update."""
        if not self._is_rotting_feature_enabled():
            self.is_rotting = False
            self.rotting_days = 0
            return
        now = self.env.cr.now()
        rot_enabled = self.filtered_domain(self._get_rotting_domain())
        others = self - rot_enabled
        for stage, records in rot_enabled.grouped(self._track_duration_field).items():
            rotting = records.filtered(
                lambda record, stage=stage: (
                    (
                        record.date_last_status_change
                        or record.create_date
                        or fields.Datetime.now()
                    )
                    + timedelta(days=stage.rotting_threshold_days)
                    < now
                )
            )
            for record in rotting:
                record.is_rotting = True
                record.rotting_days = (
                    now - (record.date_last_status_change or record.create_date)
                ).days
            others += records - rotting
        others.is_rotting = False
        others.rotting_days = 0

    def _search_is_rotting(self, operator, value):
        """Override: use date_last_status_change instead of date_last_stage_update."""
        if operator not in ["in", "not in"]:
            raise ValueError(
                self.env._(
                    'For performance reasons, use "=" operators on rotting fields.'
                )
            )
        if not self._is_rotting_feature_enabled():
            raise UserError(
                self.env._("Model configuration does not support the rotting feature")
            )
        model_depends = [
            fname for fname in self._get_rotting_depends_fields() if "." not in fname
        ]
        self.flush_model(model_depends)
        self.env[self[self._track_duration_field]._name].flush_model(
            ["rotting_threshold_days"]
        )
        base_query = self._search(self._get_rotting_domain())
        stage_table_alias_name = base_query.make_alias(
            self._table, self._track_duration_field
        )
        from_add_join = ""
        if not base_query._joins or stage_table_alias_name not in base_query._joins:
            from_add_join = """
                INNER JOIN %(stage_table)s AS %(stage_table_alias_name)s
                    ON %(stage_table_alias_name)s.id = %(table)s.%(stage_field)s
            """
        max_rotting_months = int(
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("crm.lead.rot.max.months", default=12)
        )
        query = f"""
            WITH perishables AS (
                SELECT  %(table)s.id AS id,
                        (
                            %(table)s.date_last_status_change + %(stage_table_alias_name)s.rotting_threshold_days * interval '1 day'
                        ) AS date_rot
                FROM %(from_clause)s
                    {from_add_join}
                WHERE
                    %(table)s.date_last_status_change > %(today)s - INTERVAL '%(max_rotting_months)s months'
                    AND %(where_clause)s
            )
            SELECT id
            FROM perishables
            WHERE %(today)s >= date_rot
        """
        self.env.cr.execute(
            SQL(
                query,
                table=SQL.identifier(self._table),
                stage_table=SQL.identifier(self[self._track_duration_field]._table),
                stage_table_alias_name=SQL.identifier(stage_table_alias_name),
                stage_field=SQL.identifier(self._track_duration_field),
                today=self.env.cr.now(),
                where_clause=base_query.where_clause,
                from_clause=base_query.from_clause,
                max_rotting_months=max_rotting_months,
            )
        )
        rows = self.env.cr.dictfetchall()
        return [("id", operator, [r["id"] for r in rows])]

    def _get_rotting_domain(self) -> list:
        return super()._get_rotting_domain() & Domain("is_closed", "=", False)

    @property
    def OPEN_STATES(self) -> dict[str, str]:
        """Return a list of the technical names complementing the CLOSED_STATES, a.k.a the open states"""
        return list(
            set(self._fields["state"].get_values(self.env)) - set(CLOSED_STATES)
        )

    @api.onchange("project_id")
    def _onchange_project_id(self) -> None:
        if self.state != "blocked" and self.state not in CLOSED_STATES:
            self.state = "in_progress"
        if not self.project_id and not self.user_ids:
            self.user_ids = self.env.user

        if not self.project_id and self.parent_id and self.parent_id.project_id:
            self.project_id = self.parent_id.project_id.id
            self.display_in_project = False

    def is_blocked_by_predecessors(self) -> bool:
        return any(
            blocking_task.state not in CLOSED_STATES
            for blocking_task in self.predecessor_ids
        )

    def _inverse_state(self) -> None:
        last_task_id_per_recurrence_id = (
            self.recurrence_id._get_last_task_id_per_recurrence_id()
        )
        tasks = self.filtered(
            lambda task: (
                task.state in CLOSED_STATES
                and task.id == last_task_id_per_recurrence_id.get(task.recurrence_id.id)
            )
        )
        self.env["project.task.recurrence"]._create_next_occurrences(tasks)

    @api.depends_context("uid")
    @api.depends("user_ids")
    def _compute_personal_triage_id(self) -> None:
        # An user may only access his own 'personal stage' and there can only be one pair (user, task_id)
        personal_triages = self.env["project.task.triage"].search(
            [("user_id", "=", self.env.uid), ("task_id", "in", self.ids)]
        )
        self.personal_triage_id = False
        for personal_triage in personal_triages:
            personal_triage.task_id.personal_triage_id = personal_triage

    @api.model
    def _search_personal_triage_id(self, operator: str, value: Any) -> list:
        if operator in Domain.NEGATIVE_OPERATORS:
            return NotImplemented
        # value may be a scalar (e.g. domain [("personal_triage_id", "=", 5)]);
        # normalise a local copy for the type check only — the original value is
        # what the sub-domain expects — else `for v in value` raises on an int.
        values = value if isinstance(value, (list, tuple)) else [value]
        field_name = (
            "display_name"
            if any(isinstance(v, str) for v in values)
            else "id"
        )
        domain = Domain(field_name, operator, value) & Domain(
            "user_id", "=", self.env.uid
        )
        personal_triages = self.env["project.task.triage"]._search(domain)
        return Domain("id", "in", personal_triages.subselect("task_id"))

    @api.model
    def _get_default_triage_vals(self, user_id: int) -> list[dict]:
        return [
            {
                "sequence": 1,
                "name": _("Inbox"),
                "user_id": user_id,
                "fold": False,
            },
            {
                "sequence": 2,
                "name": _("Today"),
                "user_id": user_id,
                "fold": False,
            },
            {
                "sequence": 3,
                "name": _("This Week"),
                "user_id": user_id,
                "fold": False,
            },
            {
                "sequence": 4,
                "name": _("This Month"),
                "user_id": user_id,
                "fold": False,
            },
            {
                "sequence": 5,
                "name": _("Later"),
                "user_id": user_id,
                "fold": False,
            },
            {
                "sequence": 6,
                "name": _("Done"),
                "user_id": user_id,
                "fold": True,
            },
            {
                "sequence": 7,
                "name": _("Cancelled"),
                "user_id": user_id,
                "fold": True,
            },
        ]

    def _populate_missing_triages(self) -> None:
        """Ensure every (task, assignee) pair has a triage junction row with a default bucket.

        Two-phase process:
        1. Create missing ``project.task.triage`` junction rows for all
           (task, user) pairs that don't have one yet.
        2. Assign the first triage bucket to any junction row that still has
           ``triage_id = False``.
        """
        if not self:
            return

        TaskTriage = self.env["project.task.triage"].sudo()

        # --- Phase 1: create missing junction rows ---
        existing = TaskTriage.search([("task_id", "in", self.ids)])
        existing_pairs = {(r.task_id.id, r.user_id.id) for r in existing}
        to_create = [
            {"task_id": task.id, "user_id": user.id}
            for task in self.sudo()
            for user in task.user_ids
            if (task.id, user.id) not in existing_pairs
        ]
        if to_create:
            TaskTriage.create(to_create)

        # --- Phase 2: fill in missing triage buckets ---
        triages_without_bucket = TaskTriage.search(
            [("task_id", "in", self.ids), ("triage_id", "=", False)]
        )
        if not triages_without_bucket:
            return

        triage_by_user = defaultdict(lambda: self.env["project.task.triage"])
        for task_triage in triages_without_bucket:
            triage_by_user[task_triage.user_id] |= task_triage

        for user_id, user_triages in triage_by_user.items():
            bucket = (
                self.env["project.triage"]
                .sudo()
                .search([("user_id", "=", user_id.id)], limit=1)
            )
            if not bucket:
                buckets = (
                    self.env["project.triage"]
                    .sudo()
                    .with_context(lang=user_id.partner_id.lang)
                    .create(
                        self.with_context(
                            lang=user_id.partner_id.lang
                        )._get_default_triage_vals(user_id.id)
                    )
                )
                bucket = buckets[0]
            user_triages.sudo().write({"triage_id": bucket.id})

    def message_subscribe(self, partner_ids=None, subtype_ids=None) -> bool:
        # Set task notification based on project notification preference if user follow the project
        if not subtype_ids:
            project_followers = self.project_id.sudo().message_follower_ids.filtered(
                lambda f: f.partner_id.id in partner_ids
            )
            for project_follower in project_followers:
                project_subtypes = project_follower.subtype_ids
                task_subtypes = (
                    (
                        project_subtypes.mapped("parent_id")
                        | project_subtypes.filtered(
                            lambda sub: sub.internal or sub.default
                        )
                    ).ids
                    if project_subtypes
                    else None
                )
                partner_ids.remove(project_follower.partner_id.id)
                super().message_subscribe(
                    project_follower.partner_id.ids, task_subtypes
                )
        return super().message_subscribe(partner_ids, subtype_ids)

    @api.constrains("predecessor_ids")
    def _check_no_cyclic_dependencies(self) -> None:
        if self._has_cycle("predecessor_ids"):
            raise ValidationError(_("Two tasks cannot depend on each other."))

    @api.model
    def _get_recurrence_fields(self) -> list[str]:
        return [
            "repeat_interval",
            "repeat_unit",
            "repeat_type",
            "repeat_until",
        ]

    @api.depends("recurring_task")
    def _compute_repeat(self) -> None:
        rec_fields = self._get_recurrence_fields()
        defaults = self.default_get(rec_fields)
        for task in self:
            for f in rec_fields:
                if task.recurrence_id:
                    task[f] = task.recurrence_id.sudo()[f]
                elif task.recurring_task:
                    task[f] = defaults.get(f)
                else:
                    task[f] = False

    def _is_recurrence_valid(self) -> bool:
        self.ensure_one()
        return self.repeat_interval > 0 and (
            self.repeat_type != "until"
            or (self.repeat_until and self.repeat_until > fields.Date.today())
        )

    @api.depends("recurrence_id")
    def _compute_recurring_count(self) -> None:
        self.recurring_count = 0
        recurring_tasks = self.filtered(lambda l: l.recurrence_id)
        count = self.env["project.task"]._read_group(
            [("recurrence_id", "in", recurring_tasks.recurrence_id.ids)],
            ["recurrence_id"],
            ["__count"],
        )
        tasks_count = {recurrence.id: count for recurrence, count in count}
        for task in recurring_tasks:
            task.recurring_count = tasks_count.get(task.recurrence_id.id, 0)

    @api.depends("predecessor_ids", "predecessor_ids.state")
    def _compute_predecessor_count(self) -> None:
        tasks_with_dependency = self.filtered("allow_dependencies")
        tasks_without_dependency = self - tasks_with_dependency
        tasks_without_dependency.predecessor_count = 0
        tasks_without_dependency.closed_predecessor_count = 0
        if not any(self._ids):
            for task in self:
                task.predecessor_count = len(task.predecessor_ids)
                task.closed_predecessor_count = len(
                    task.predecessor_ids.filtered(lambda r: r.state in CLOSED_STATES)
                )
            return
        if tasks_with_dependency:
            # need the sudo for project sharing
            total_and_closed_predecessor_count = {
                dependent_on.id: (
                    count,
                    sum(s in CLOSED_STATES for s in states),
                )
                for dependent_on, states, count in self.env["project.task"]._read_group(
                    [("successor_ids", "in", tasks_with_dependency.ids)],
                    ["successor_ids"],
                    ["state:array_agg", "__count"],
                )
            }
            for task in tasks_with_dependency:
                task.predecessor_count, task.closed_predecessor_count = (
                    total_and_closed_predecessor_count.get(
                        task._origin.id or task.id, (0, 0)
                    )
                )

    @api.depends("successor_ids", "successor_ids.is_closed")
    def _compute_successor_count(self) -> None:
        tasks_with_dependency = self.filtered("allow_dependencies")
        (self - tasks_with_dependency).successor_count = 0
        if tasks_with_dependency:
            group_dependent = self.env["project.task"]._read_group(
                [
                    ("predecessor_ids", "in", tasks_with_dependency.ids),
                    ("is_closed", "=", False),
                ],
                ["predecessor_ids"],
                ["__count"],
            )
            successor_count_dict = {
                depend_on.id: count for depend_on, count in group_dependent
            }
            for task in tasks_with_dependency:
                task.successor_count = successor_count_dict.get(task.id, 0)

    @api.constrains("parent_id")
    def _check_parent_id(self) -> None:
        if self._has_cycle():
            raise ValidationError(
                _("Error! You cannot create a recursive hierarchy of tasks.")
            )

    def _get_attachments_search_domain(self) -> list:
        self.ensure_one()
        return [("res_id", "=", self.id), ("res_model", "=", "project.task")]

    def _compute_attachment_ids(self) -> None:
        # Batch the attachment lookup for the whole recordset (one query instead
        # of one search per task): this field is read in kanban/list prefetch.
        attachments_by_task: dict[int, list[int]] = {}
        if self.ids:
            attachment_data = self.env["ir.attachment"]._read_group(
                [("res_model", "=", "project.task"), ("res_id", "in", self.ids)],
                ["res_id"],
                ["id:array_agg"],
            )
            attachments_by_task = dict(attachment_data)
        for task in self:
            attachment_ids = attachments_by_task.get(task.id, [])
            message_attachment_ids = task.mapped(
                "message_ids.attachment_ids"
            ).ids  # from mail_thread
            task.attachment_ids = [
                (6, 0, list(set(attachment_ids) - set(message_attachment_ids)))
            ]

    @api.depends(
        "create_date",
        "date_closed",
        "date_assign",
        "project_id.resource_calendar_id",
    )
    def _compute_elapsed(self) -> None:
        """Compute queue time, lead time, and cycle time (calendar-adjusted)."""
        task_linked_to_calendar = self.filtered(
            lambda task: task.project_id.resource_calendar_id and task.create_date
        )
        for task in task_linked_to_calendar:
            dt_create = fields.Datetime.from_string(task.create_date)
            calendar = task.project_id.resource_calendar_id
            leave_domain = [
                ("company_id", "in", task.project_id.company_id.ids),
                ("time_type", "=", "leave"),
            ]

            # Queue time: create → assign
            if task.date_assign:
                dt_assign = fields.Datetime.from_string(task.date_assign)
                data = calendar.get_work_duration_data(
                    dt_create,
                    dt_assign,
                    compute_leaves=True,
                    domain=leave_domain,
                )
                task.queue_time_hours = data["hours"]
                task.queue_time_days = data["days"]
            else:
                task.queue_time_hours = 0.0
                task.queue_time_days = 0.0

            # Lead time: create → closed
            if task.date_closed:
                dt_end = fields.Datetime.from_string(task.date_closed)
                data = calendar.get_work_duration_data(
                    dt_create,
                    dt_end,
                    compute_leaves=True,
                    domain=leave_domain,
                )
                task.lead_time_hours = data["hours"]
                task.lead_time_days = data["days"]
            else:
                task.lead_time_hours = 0.0
                task.lead_time_days = 0.0

            # Cycle time: assign → closed (requires both dates)
            if task.date_assign and task.date_closed:
                dt_assign = fields.Datetime.from_string(task.date_assign)
                dt_end = fields.Datetime.from_string(task.date_closed)
                data = calendar.get_work_duration_data(
                    dt_assign,
                    dt_end,
                    compute_leaves=True,
                    domain=leave_domain,
                )
                task.cycle_time_hours = data["hours"]
                task.cycle_time_days = data["days"]
            else:
                task.cycle_time_hours = 0.0
                task.cycle_time_days = 0.0

        (self - task_linked_to_calendar).update(
            dict.fromkeys(
                [
                    "queue_time_hours",
                    "queue_time_days",
                    "lead_time_hours",
                    "lead_time_days",
                    "cycle_time_hours",
                    "cycle_time_days",
                ],
                0.0,
            )
        )

    @api.depends("date_closed", "date_end", "state")
    def _compute_deadline_met(self) -> None:
        """Determine whether a closed task met its deadline.

        Tri-state: empty (no deadline, or not yet closed), 'met', or 'missed'.
        The empty case must stay distinct from 'missed' so reports don't count
        deadline-less closed tasks as late.
        """
        for task in self:
            if not task.date_end or task.state not in CLOSED_STATES:
                task.deadline_met = False
            elif task.date_closed and task.date_closed <= task.date_end:
                task.deadline_met = "met"
            else:
                task.deadline_met = "missed"

    @api.depends("cost_of_delay", "planned_hours")
    def _compute_cd3_score(self) -> None:
        """Compute Cost of Delay Divided by Duration for value-based prioritization.

        Uses ``planned_hours`` (estimate-based) so prioritization works
        even before resources are assigned.  See PMI hours model.
        """
        for task in self:
            if task.cost_of_delay and task.planned_hours:
                task.cd3_score = task.cost_of_delay / task.planned_hours
            else:
                task.cd3_score = 0.0

    @api.depends("reservation_ids.schedule_overlap_count")
    def _compute_is_overallocated(self) -> None:
        """Concurrent overcommit on any of this task's reservations.

        Delegates to ``resource.reservation.schedule_overlap_count``,
        which counts other reservations of the same resource overlapping
        in time AND summing > 100% allocation.  Captures real PMBOK
        overallocation (concurrency, not lifetime backlog volume).
        """
        for task in self:
            task.is_overallocated = any(
                r.schedule_overlap_count for r in task.reservation_ids
            )

    def _compute_access_url(self) -> None:
        super()._compute_access_url()
        for task in self:
            task.access_url = f"/my/tasks/{task.id}"

    @api.depends("child_ids.planned_hours")
    def _compute_subtask_planned_hours(self) -> None:
        for task in self:
            task.subtask_planned_hours = sum(task.child_ids.mapped("planned_hours"))

    @api.depends(
        "planned_date_begin",
        "date_end",
        "company_id",
    )
    def _compute_scheduled_hours(self) -> None:
        """Working hours within the task's scheduled range."""
        for task in self:
            task.scheduled_hours = round(
                task._scheduling_get_work_hours(
                    task.planned_date_begin,
                    task.date_end,
                    compute_leaves=True,
                ),
                2,
            )

    @api.depends("scheduled_hours", "planned_resources", "allocated_percentage")
    def _compute_planned_hours(self) -> None:
        """PMBOK Effort = Duration x Resources x Units (uniform rate)."""
        for task in self:
            task.planned_hours = round(
                task.scheduled_hours
                * task.planned_resources
                * (task.allocated_percentage / 100.0),
                2,
            )

    def _inverse_planned_hours(self) -> None:
        """Track manual overrides of the PMBOK-derived planned_hours.

        ``planned_hours`` is a stored compute with ``readonly=False``: Odoo
        calls this inverse only on direct user writes, not on
        dependency-driven recomputes.  Posting from here keeps the chatter
        signal precise (override events) without the noise that
        ``tracking=True`` would generate on every formula recompute.
        """
        for task in self:
            task.message_post(
                body=_(
                    "Planned Hours manually overridden to %(value).2f h "
                    "(formula override).",
                    value=task.planned_hours,
                ),
            )

    @api.depends("planned_hours", "allocated_hours")
    def _compute_allocation_state(self) -> None:
        """Resource allocation health relative to plan."""
        for task in self:
            if float_is_zero(task.planned_hours, precision_digits=2):
                task.allocation_state = "unestimated"
                continue
            if float_is_zero(task.allocated_hours, precision_digits=2):
                task.allocation_state = "unallocated"
                continue
            delta = float_compare(
                task.allocated_hours, task.planned_hours, precision_digits=2
            )
            if delta == 0:
                task.allocation_state = "allocated"
            elif delta > 0:
                task.allocation_state = "over_allocated"
            else:
                task.allocation_state = "under_allocated"

    @api.depends("child_ids", "child_ids.state")
    def _compute_subtask_count(self) -> None:
        if not any(self._ids):
            for task in self:
                task.subtask_count, task.closed_subtask_count = (
                    len(task.child_ids),
                    len(task.child_ids.filtered(lambda r: r.state in CLOSED_STATES)),
                )
            return
        total_and_closed_subtask_count_per_parent_id = {
            parent.id: (count, sum(s in CLOSED_STATES for s in states))
            for parent, states, count in self.env["project.task"]._read_group(
                [("parent_id", "in", self.ids)],
                ["parent_id"],
                ["state:array_agg", "__count"],
            )
        }
        for task in self:
            task.subtask_count, task.closed_subtask_count = (
                total_and_closed_subtask_count_per_parent_id.get(task.id, (0, 0))
            )

    @api.depends("partner_id.phone")
    def _compute_partner_phone(self) -> None:
        for task in self:
            task.partner_phone = task.partner_id.phone or False

    def _inverse_partner_phone(self) -> None:
        for task in self:
            if task.partner_id and task.partner_phone != task.partner_id.phone:
                task.partner_id.sudo().phone = task.partner_phone

    @api.onchange("company_id")
    def _onchange_task_company(self) -> None:
        if self.project_id.company_id and self.project_id.company_id != self.company_id:
            self.project_id = False

    @api.depends("project_id.company_id", "parent_id.company_id")
    def _compute_company_id(self) -> None:
        for task in self:
            if not task.parent_id and not task.project_id:
                continue
            task.company_id = task.project_id.company_id or task.parent_id.company_id

    @api.depends("project_id")
    def _compute_step_id(self) -> None:
        # The default step only depends on the target project, so resolve it
        # once per distinct project instead of running step_find per task
        # (matters when moving/duplicating many tasks at once).
        default_step_by_project: dict[int, int | bool] = {}
        for task in self:
            project = task.project_id or task.parent_id.project_id
            if not project:
                task.step_id = False
                continue
            if project not in task.step_id.project_ids:
                if project.id not in default_step_by_project:
                    default_step_by_project[project.id] = task.step_find(
                        project.id, [("fold", "=", False)]
                    )
                task.step_id = default_step_by_project[project.id]

    @api.depends("user_ids")
    def _compute_portal_user_names(self) -> None:
        """This compute method allows to see all the names of assigned users to each task contained in `self`.

        When we are in the project sharing feature, the `user_ids` contains only the users if we are a portal user.
        That is, only the users in the same company of the current user.
        So this compute method is a related of `user_ids.name` but with more records that the portal user
        can normally see.
        (In other words, this compute is only used in project sharing views to see all assignees for each task)
        """
        if self._origin:
            # fetch 'user_ids' in superuser mode (and override value in cache
            # browse is useful to avoid miscache because of the newIds contained in self
            self.invalidate_recordset(fnames=["user_ids"])
            self._origin.fetch(["user_ids"])
        for task in self.with_context(prefetch_fields=False):
            task.portal_user_names = format_list(self.env, task.user_ids.mapped("name"))

    def _search_portal_user_names(self, operator: str, value: Any) -> list:
        if operator != "ilike" or not isinstance(value, str):
            return NotImplemented

        sql = SQL(
            """(
            SELECT task_user.task_id
              FROM project_task_user_rel task_user
        INNER JOIN res_users users ON task_user.user_id = users.id
        INNER JOIN res_partner partners ON partners.id = users.partner_id
             WHERE partners.name ILIKE %s
        )""",
            f"%{value}%",
        )
        return [("id", "in", sql)]

    def _compute_display_parent_task_button(self) -> None:
        accessible_parent_tasks = self.parent_id.with_user(
            self.env.user
        )._filtered_access("read")
        for task in self:
            task.display_parent_task_button = task.parent_id in accessible_parent_tasks

    def _compute_current_user_same_company_partner(self) -> None:
        commercial_partner_id = self.env.user.partner_id.commercial_partner_id
        for task in self:
            task.current_user_same_company_partner = (
                task.partner_id
                and commercial_partner_id == task.partner_id.commercial_partner_id
            )

    def _compute_display_follow_button(self) -> None:
        if not self.env.user.share:
            self.display_follow_button = False
            return
        project_collaborator_read_group = self.env["project.collaborator"]._read_group(
            [
                ("project_id", "in", self.project_id.ids),
                ("partner_id", "=", self.env.user.partner_id.id),
            ],
            ["project_id"],
            ["limited_access:bool_and"],
        )
        limited_access_per_project_id = dict(project_collaborator_read_group)
        for task in self:
            task.display_follow_button = not limited_access_per_project_id.get(
                task.project_id, True
            )

    def _get_group_pattern(self) -> str:
        return {
            "tags_and_users": r"\s([#@]%s[^\s]+)",
            "priority": r"(?:^|\s)(!{1,3})(?=\s|$)",
        }

    def _prepare_pattern_groups(self) -> str:
        group = self._get_group_pattern()
        return [
            group["tags_and_users"] % "",
            group["priority"],
        ]

    def _get_groups_patterns(self) -> str:
        return [
            r"(?:%s)*" % ("|").join(self._prepare_pattern_groups()),
        ]

    def _get_cannot_start_with_patterns(self) -> str:
        return [r"(?![#!@\s])"]

    def _extract_tags_and_users(self) -> tuple:
        tags = []
        users = []
        tags_and_users_group = self._get_group_pattern()["tags_and_users"]
        for word in re.findall(tags_and_users_group % "", self.display_name):
            (tags if word.startswith("#") else users).append(word[1:])
        users_to_keep = []
        user_ids = []
        for user in users:
            matched_users = self.env["res.users"].name_search(user)
            if len(matched_users) == 1:
                user_ids.append(Command.link(matched_users[0][0]))
            else:
                users_to_keep.append(r"%s\b" % user)
        self.user_ids = user_ids
        if tags:
            domain = Domain.OR(Domain("name", "=ilike", tag) for tag in tags)
            existing_tags = self.env["project.tags"].search(domain)
            existing_tags_names = {tag.name.lower() for tag in existing_tags}
            new_tags_names = {
                tag for tag in tags if tag.lower() not in existing_tags_names
            }
            self.tag_ids = [Command.set(existing_tags.ids)] + [
                Command.create({"name": name}) for name in new_tags_names
            ]
        pattern = tags_and_users_group % (
            "(?!%s)" % ("|").join(users_to_keep) if users_to_keep else ""
        )
        self.display_name, _ = re.subn(pattern, "", self.display_name)

    def _extract_priority(self) -> str | None:
        priority_group = self._get_group_pattern()["priority"]
        match = re.search(priority_group, self.display_name)
        if match:
            self.priority = str(min(len(match.group(1)), 3))
            self.display_name, _dummy = re.subn(priority_group, "", self.display_name)

    def _get_groups(self) -> dict:
        return [
            lambda task: task._extract_tags_and_users(),
            lambda task: task._extract_priority(),
        ]

    def _inverse_display_name(self) -> None:
        for task in self:
            if not task.display_name:
                continue
            pattern = re.compile(
                r"^%s.+?%s$"
                % (
                    ("").join(task._get_cannot_start_with_patterns()),
                    ("").join(task._get_groups_patterns()),
                )
            )
            match = pattern.match(task.display_name)
            if match:
                for group, extract_data in enumerate(task._get_groups(), start=1):
                    if match.group(group):
                        extract_data(task)
                task.name = task.display_name.strip()

    def _compute_link_preview_name(self) -> None:
        for task in self:
            link_preview_name = task.display_name
            if task.project_id:
                link_preview_name += f" | {task.project_id.sudo().name}"
            task.link_preview_name = link_preview_name

    @api.depends("is_template", "parent_id.has_template_ancestor")
    def _compute_has_template_ancestor(self) -> None:
        for task in self:
            task.has_template_ancestor = task.is_template or (
                task.parent_id and task.parent_id.sudo().has_template_ancestor
            )

    def _search_has_template_ancestor(self, operator: str, value: Any) -> list:
        if operator not in ["=", "!="] or not isinstance(value, bool):
            return NotImplemented
        template_tasks = (
            self.env["project.task"]
            .with_context(active_test=False)
            .sudo()
            .search([("is_template", "=", True)])
        )
        domain = [("id", "child_of", template_tasks.ids)]
        if (operator == "=") != value:
            domain = ["!", ("id", "child_of", template_tasks.ids)]
        return domain

    def copy_data(self, default=None) -> list[dict]:
        default = dict(default or {})
        default.update(
            {
                "predecessor_ids": False,
                "successor_ids": False,
            }
        )
        vals_list = super().copy_data(default=default)
        # filter only readable fields
        vals_list = [
            {
                k: v
                for k, v in vals.items()
                if self._has_field_access(self._fields[k], "read")
            }
            for vals in vals_list
        ]

        active_users = self.env["res.users"]
        has_default_users = "user_ids" in default
        if not has_default_users:
            active_users = self.user_ids.filtered("active")
        milestone_mapping = self.env.context.get("milestone_mapping", {})
        for task, vals in zip(self, vals_list, strict=True):
            if not default.get("step_id"):
                vals["step_id"] = task.step_id.id
            if (
                "active" not in default
                and not task["active"]
                and not self.env.context.get("copy_project")
            ):
                vals["active"] = True
            if not default.get("name"):
                vals["name"] = (
                    task.name
                    if self.env.context.get("copy_project")
                    or self.env.context.get("copy_from_template")
                    else _("%s (copy)", task.name)
                )
            if task.recurrence_id and not default.get("recurrence_id"):
                vals["recurrence_id"] = task.recurrence_id.copy().id
            if task.allow_milestones:
                vals["milestone_id"] = milestone_mapping.get(
                    vals["milestone_id"], vals["milestone_id"]
                )
            if not default.get("child_ids") and task.child_ids:
                whitelisted_fields = (
                    self._get_template_default_context_whitelist()
                    if self.env.context.get("copy_from_template")
                    else []
                )
                # Use a distinct dict for the recursive child copy — rebinding
                # the loop-shared `default` here would narrow the caller's
                # defaults for every subsequent task in this batch.
                child_default = {
                    key: value
                    for key, value in default.items()
                    if key in whitelisted_fields
                }
                child_default["parent_id"] = False
                current_task = task
                if self.env.context.get("copy_from_template"):
                    current_task = current_task.with_context(active_test=True)
                child_ids = current_task.child_ids
                vals["child_ids"] = [
                    Command.create(child_id.copy_data(child_default)[0])
                    for child_id in child_ids.filtered(lambda c: c.active)
                ]
            if not has_default_users and vals["user_ids"]:
                task_active_users = task.user_ids & active_users
                vals["user_ids"] = [Command.set(task_active_users.ids)]
            if self.env.context.get("copy_from_template") and not self.env.context.get(
                "copy_from_project_template"
            ):
                vals["is_template"] = False
            if self.env.context.get("copy_from_template"):
                for field in set(self._get_template_field_blacklist()) & set(
                    vals.keys()
                ):
                    del vals[field]
        return vals_list

    def _create_task_mapping(self, copied_tasks: Self) -> dict:
        """Thanks to the way create and command.create is handled, when a task with 2 children is copied, we have the guarantee that the children of the
        copied task will have the same index in the child_ids recordset. We can use this behavior to create a mapping containing all the original tasks and their copy.
        :return:
            task_mapping: a dict containing the mapping of the original task ids and their copied task (k: original_task.id, v: new_task)
            task_dependencies: a dict containing the ids of the dependencies of the original task when they have one.
            (k: original_task_id, v: [original_task.predecessor_ids.ids, original_task.successor_ids.ids]
        """
        task_mapping, task_dependencies = {}, {}
        # `copied_tasks` (read back as a child_ids/One2many) is returned in the
        # model's _order, which does NOT match `self`'s iteration order — so a
        # positional zip mis-pairs originals with copies (and, one level down,
        # zips a parent's real children against the wrong copy's empty child set,
        # raising `zip strict`). copy_data builds the copies by iterating this
        # same `self` and Command.create assigns ids in creation order, so the
        # i-th original corresponds to the i-th *smallest copied id*. Sort the
        # copies by id to restore that correspondence.
        copied_tasks = copied_tasks.sorted("id")
        for original_task, copied_task in zip(self, copied_tasks, strict=True):
            task_mapping[original_task.id] = copied_task
            if original_task.allow_dependencies and (
                original_task.predecessor_ids or original_task.successor_ids
            ):
                task_dependencies[original_task.id] = [
                    original_task.predecessor_ids.ids,
                    original_task.successor_ids.ids,
                ]
            # Only active children are duplicated by copy_data (archived subtasks
            # are skipped), so the mapping must walk the same active-only set —
            # otherwise the strict zip above blows up when an archived subtask
            # exists (project duplication would crash).
            active_children = original_task.child_ids.filtered("active")
            if active_children:
                # If the task has children, we have to call the method create_task_mapping to get their ids and dependencies mapping too.
                children_mapping, children_dependencies = (
                    active_children._create_task_mapping(copied_task.child_ids)
                )
                task_mapping.update(children_mapping)
                task_dependencies.update(children_dependencies)
        return task_mapping, task_dependencies

    def _portal_get_parent_hash_token(self, pid: int) -> str:
        return self.project_id._sign_token(pid)

    def _resolve_copied_dependencies(self, copied_tasks: Self) -> None:
        task_mapping, task_dependencies = self._create_task_mapping(copied_tasks)

        for original_task_id, (
            predecessor_ids,
            successor_ids,
        ) in task_dependencies.items():
            # If one of the task_id in the dependencies mapping is also a key of the task_mapping, it means that this task was copied too.
            # In this case, we should exchange this id with the id of the corresponding copied task
            task_mapping[original_task_id].predecessor_ids = [
                (task_id if task_id not in task_mapping else task_mapping[task_id].id)
                for task_id in predecessor_ids
            ]
            task_mapping[original_task_id].successor_ids = [
                (task_id if task_id not in task_mapping else task_mapping[task_id].id)
                for task_id in successor_ids
            ]

    def copy(self, default=None) -> Self:
        default = default or {}
        copied_tasks = super(
            ProjectTask,
            self.with_context(
                mail_auto_subscribe_no_notify=True,
                mail_create_nosubscribe=True,
                mail_create_nolog=bool(not self.env.context.get("copy_from_template")),
            ),
        ).copy(default=default)

        self._resolve_copied_dependencies(copied_tasks)
        if not self.env.context.get("copy_from_template"):
            log_message = _("Task Created")
            copied_tasks._message_log_batch(
                bodies={task.id: log_message for task in copied_tasks}
            )

        return copied_tasks

    @api.model
    def get_empty_list_help(self, help_message: str) -> str:
        tname = _("task")
        project_id = self.env.context.get("default_project_id", False)
        if project_id:
            name = self.env["project.project"].browse(project_id).label_tasks
            if name:
                tname = name.lower()

        self = self.with_context(
            empty_list_help_id=self.env.context.get("default_project_id"),
            empty_list_help_model="project.project",
            empty_list_help_document_name=tname,
        )
        return super().get_empty_list_help(help_message)

    # ----------------------------------------
    # Case management
    # ----------------------------------------

    def step_find(
        self,
        section_id: int | bool,
        domain: list | None = None,
        order: str = "sequence, id",
    ) -> int | bool:
        """Override of the base.stage method
        Parameter of the stage search taken from the lead:

        :param section_id: if set, stages must belong to this section or
            be a default stage; if not set, stages must be default stages
        """
        # collect all section_ids
        domain = domain or []
        section_ids = []
        if section_id:
            section_ids.append(section_id)
        section_ids.extend(self.mapped("project_id").ids)
        search_domain = []
        if section_ids:
            search_domain = ["|"] * (len(section_ids) - 1)
            for sec_id in section_ids:
                search_domain.append(("project_ids", "=", sec_id))
        search_domain += list(domain)
        # perform search, return the first found
        return (
            self.env["project.workflow.step"]
            .search(search_domain, order=order, limit=1)
            .id
        )

    # ------------------------------------------------
    # CRUD overrides
    # ------------------------------------------------

    @api.model
    def _get_view_cache_key(
        self,
        view_id: int | None = None,
        view_type: str = "form",
        **options: Any,
    ) -> tuple:
        """The override of fields_get making fields readonly for portal users
        makes the view cache dependent on the fact the user has the group portal or not
        """
        key = super()._get_view_cache_key(view_id, view_type, **options)
        return key + (self.env.user._is_portal(),)

    @api.model
    def default_get(self, fields: list[str]) -> dict:
        vals = super().default_get(fields)

        if project_id := self.env.context.get("default_create_in_project_id"):
            vals["project_id"] = project_id

        # prevent creating new task in the waiting state
        if "state" in fields and vals.get("state") == "blocked":
            vals["state"] = "in_progress"

        if "repeat_until" in fields:
            vals["repeat_until"] = Date.today() + timedelta(days=7)

        if "partner_id" in vals and not vals["partner_id"]:
            # if the default_partner_id=False or no default_partner_id then we search the partner based on the project and parent
            project_id = vals.get("project_id")
            parent_id = vals.get("parent_id", self.env.context.get("default_parent_id"))
            if project_id or parent_id:
                partner_id = self._get_default_partner_id(
                    project_id and self.env["project.project"].browse(project_id),
                    parent_id and self.env["project.task"].browse(parent_id),
                )
                if partner_id:
                    vals["partner_id"] = partner_id
        project_id = vals.get("project_id", self.env.context.get("default_project_id"))
        if project_id:
            project = self.env["project.project"].browse(project_id)
            if "company_id" in fields and "default_project_id" not in self.env.context:
                vals["company_id"] = project.sudo().company_id.id
        elif "default_user_ids" not in self.env.context and "user_ids" in fields:
            user_ids = vals.get("user_ids", [])
            user_ids.append(Command.link(self.env.user.id))
            vals["user_ids"] = user_ids

        parent_id = vals.get("parent_id", self.env.context.get("default_parent_id"))
        if parent_id:
            parent = self.env["project.task"].browse(parent_id)
            if not vals.get("tag_ids"):
                vals["tag_ids"] = parent.tag_ids

        return vals

    @api.model
    @tools.ormcache(cache="stable")
    def _portal_accessible_fields(
        self,
    ) -> tuple[frozenset[str], frozenset[str]]:
        """Readable and writable fields by portal users."""
        readable = frozenset(self.TASK_PORTAL_READABLE_FIELDS)
        writeable = frozenset(self.TASK_PORTAL_WRITABLE_FIELDS)
        return readable | writeable, writeable

    def _has_field_access(self, field: Any, operation: str) -> bool:
        if not super()._has_field_access(field, operation):
            return False
        if not self.env.su and self.env.user._is_portal():
            # additional checks for portal users
            readable, writeable = self._portal_accessible_fields()
            if operation == "read":
                return field.name in readable
            if operation == "write":
                return field.name in writeable
        return True

    def _ensure_fields_write(
        self, vals: dict[str, Any], defaults: bool = False
    ) -> None:
        if defaults:
            vals = {
                **{
                    key[8:]: value
                    for key, value in self.env.context.items()
                    if key.startswith("default_") and key[8:] in self._fields
                },
                **vals,
            }

        for fname, value in vals.items():
            field = self._fields.get(fname)
            if field and field.type == "many2one":
                self.env[field.comodel_name].browse(value).check_access("read")

    def _set_step_on_project_from_task(self) -> None:
        step_ids_per_project = defaultdict(list)
        for task in self:
            if (
                task.step_id
                and task.step_id not in task.project_id.workflow_step_ids
                and task.step_id.id not in step_ids_per_project[task.project_id]
            ):
                step_ids_per_project[task.project_id].append(task.step_id.id)

        for project, step_ids in step_ids_per_project.items():
            project.write(
                {"workflow_step_ids": [Command.link(step_id) for step_id in step_ids]}
            )

    def _load_records_create(self, vals_list: list[dict[str, Any]]) -> Self:
        for vals in vals_list:
            if vals.get("recurring_task"):
                rec_fields = vals.keys() & self._get_recurrence_fields()
                if not vals.get("recurrence_id") and not rec_fields:
                    default_val = self.default_get(self._get_recurrence_fields())
                    vals.update(**default_val)
            project_id = vals.get("project_id")
            if project_id:
                self = self.with_context(default_project_id=project_id)
        return super()._load_records_create(vals_list)

    @api.model_create_multi
    def create(self, vals_list: list[dict[str, Any]]) -> Self:
        # Some values are determined by this override and must be written as
        # sudo for portal users, because they do not have access to these
        # fields. Other values must not be written as sudo.
        additional_vals_list = [{} for _ in vals_list]

        new_context = dict(self.env.context)
        default_triage = new_context.pop("default_triage_ids", False)
        default_project_id = new_context.pop("default_project_id", False)
        if not default_project_id:
            parent_task = self.browse(
                {
                    parent_id
                    for vals in vals_list
                    if (parent_id := vals.get("parent_id"))
                }
            )
            if len(parent_task) == 1:
                default_project_id = parent_task.sudo().project_id.id
        # (portal) users that don't have write access can still create a task
        # in the project that will be checked using record rules
        new_context["default_create_in_project_id"] = default_project_id
        if not self._has_field_access(self._fields["user_ids"], "write"):
            # remove user_ids if we have no access to it
            new_context.pop("default_user_ids", False)
        self_ctx = self.with_context(new_context)

        self_ctx.browse().check_access("create")
        default_stage = {}
        for vals, additional_vals in zip(vals_list, additional_vals_list, strict=True):
            project_id = vals.get("project_id") or default_project_id

            if vals.get("user_ids"):
                additional_vals["date_assign"] = fields.Datetime.now()
                if not (vals.get("parent_id") or project_id):
                    user_ids = self_ctx._fields["user_ids"].convert_to_cache(
                        vals.get("user_ids", []), self_ctx.env["project.task"]
                    )
                    if self_ctx.env.user.id not in list(user_ids) + [SUPERUSER_ID]:
                        additional_vals["user_ids"] = [
                            Command.set(list(user_ids) + [self_ctx.env.user.id])
                        ]
            if default_triage and "triage_id" not in vals:
                additional_vals["triage_id"] = default_triage[0]
            if not vals.get("name") and vals.get("display_name"):
                vals["name"] = vals["display_name"]

            if self_ctx.env.user._is_portal() and not self_ctx.env.su:
                self_ctx._ensure_fields_write(vals, defaults=True)

            if project_id and "company_id" not in vals:
                additional_vals["company_id"] = (
                    self_ctx.env["project.project"].browse(project_id).company_id.id
                )
            if not project_id and (
                "step_id" in vals or self_ctx.env.context.get("default_step_id")
            ):
                vals["step_id"] = False

            if project_id and "step_id" not in vals:
                # 1) Allows keeping the batch creation of tasks
                # 2) Ensure the defaults are correct (and computed once by project),
                # by using default get (instead of _get_default_step_id or _step_find),
                if project_id not in default_stage:
                    default_stage[project_id] = (
                        self_ctx.with_context(default_project_id=project_id)
                        .default_get(["step_id"])
                        .get("step_id")
                    )
                vals["step_id"] = default_stage[project_id]

            # Step change: Update date_closed if folded stage and date_last_status_change
            if vals.get("step_id"):
                additional_vals.update(self_ctx.update_date_closed(vals["step_id"]))
                additional_vals["date_last_status_change"] = fields.Datetime.now()
            # recurrence
            rec_fields = vals.keys() & self_ctx._get_recurrence_fields()
            if rec_fields and vals.get("recurring_task") is True:
                rec_values = {rec_field: vals[rec_field] for rec_field in rec_fields}
                recurrence = self_ctx.env["project.task.recurrence"].create(rec_values)
                vals["recurrence_id"] = recurrence.id

        # create the task, write computed inaccessible fields in sudo
        for vals, computed_vals in zip(vals_list, additional_vals_list, strict=True):
            for field_name in list(computed_vals):
                if self_ctx._has_field_access(self_ctx._fields[field_name], "write"):
                    vals[field_name] = computed_vals.pop(field_name)
        # no track when the portal user create a task to avoid using during tracking
        # process since the portal does not have access to tracking models
        tasks = super(
            ProjectTask,
            self_ctx.with_context(
                mail_create_nosubscribe=True,
                mail_notrack=not self_ctx.env.su and self_ctx.env.user._is_portal(),
            ),
        ).create(vals_list)
        for task, computed_vals in zip(tasks.sudo(), additional_vals_list, strict=True):
            if computed_vals:
                task.write(computed_vals)
        tasks.sudo()._populate_missing_triages()
        self_ctx._task_message_auto_subscribe_notify(
            {task: task.user_ids - self_ctx.env.user for task in tasks}
        )

        current_partner = self_ctx.env.user.partner_id

        all_partner_emails = []
        for task in tasks.sudo():
            all_partner_emails += tools.email_normalize_all(task.email_cc)
        partners = self_ctx.env["res.partner"].search(
            [("email", "in", all_partner_emails)]
        )
        partner_per_email = {
            partner.email: partner
            for partner in partners
            if not all(u.share for u in partner.user_ids)
        }
        if tasks.project_id:
            tasks.sudo()._set_step_on_project_from_task()
        for task in tasks.sudo():
            if task.project_id.privacy_visibility in [
                "invited_users",
                "portal",
            ]:
                task._portal_ensure_token()
            for follower in task.parent_id.message_follower_ids:
                task.message_subscribe(
                    follower.partner_id.ids, follower.subtype_ids.ids
                )
            if current_partner not in task.message_partner_ids:
                task.message_subscribe(current_partner.ids)
            if task.email_cc:
                partners_with_internal_user = self_ctx.env["res.partner"]
                for email in tools.email_normalize_all(task.email_cc):
                    new_partner = partner_per_email.get(email)
                    if new_partner:
                        partners_with_internal_user |= new_partner
                if not partners_with_internal_user:
                    continue
                task._send_email_notify_to_cc(partners_with_internal_user)
                task.message_subscribe(partners_with_internal_user.ids)
        return tasks

    def write(self, vals: dict[str, Any]) -> bool:
        self.check_access("write")
        if len(self) == 1:
            handle_history_divergence(self, "description", vals)
        partner_ids = []

        # Some values are determined by this override and must be written as
        # sudo for portal users, because they do not have access to these
        # fields. Other values must not be written as sudo.
        additional_vals = {}
        if self.env.user._is_portal() and not self.env.su:
            self._ensure_fields_write(vals, defaults=False)

        if "milestone_id" in vals:
            # WARNING: has to be done after 'project_id' vals is written on subtasks
            # Capture the target milestone id up front: `vals["milestone_id"]` may be
            # popped below (branch 1) yet is still needed for the subtask propagation.
            milestone_id_val = vals["milestone_id"]
            milestone = self.env["project.milestone"].browse(milestone_id_val)

            # 1. Task for which the milestone is unvalid -> milestone_id is reset
            if "project_id" not in vals:
                unvalid_milestone_tasks = (
                    self.filtered(lambda task: task.project_id != milestone.project_id)
                    if vals["milestone_id"]
                    else self.env["project.task"]
                )
            else:
                unvalid_milestone_tasks = (
                    self
                    if not vals["milestone_id"]
                    or milestone.project_id.id != vals["project_id"]
                    else self.env["project.task"]
                )
            valid_milestone_tasks = self - unvalid_milestone_tasks
            if unvalid_milestone_tasks:
                unvalid_milestone_tasks.sudo().write({"milestone_id": False})
                if valid_milestone_tasks:
                    valid_milestone_tasks.sudo().write(
                        {"milestone_id": milestone_id_val}
                    )
                del vals["milestone_id"]

            # 2. Parent's milestone is set to subtask with no milestone recursively
            subtasks_to_update = valid_milestone_tasks.child_ids.filtered(
                lambda task: (
                    task not in self
                    and not task.milestone_id
                    and task.project_id == milestone.project_id
                    and task.state not in CLOSED_STATES
                )
            )

            # 3. If parent and child task share the same milestone, child task's milestone is updated when the parent one is changed
            # No need to check if state is changed in vals as it won't affect the subtasks selected for update
            if "project_id" not in vals:
                subtasks_to_update |= valid_milestone_tasks.child_ids.filtered(
                    lambda task: (
                        task not in self
                        and task.milestone_id == task.parent_id.milestone_id
                        and task.state not in CLOSED_STATES
                    )
                )
            else:
                subtasks_to_update |= valid_milestone_tasks.child_ids.filtered(
                    lambda task: (
                        task not in self
                        and (
                            not task.display_in_project
                            or task.project_id.id == vals["project_id"]
                        )
                        and task.milestone_id == task.parent_id.milestone_id
                        and task.state not in CLOSED_STATES
                    )
                )
            if subtasks_to_update:
                subtasks_to_update.sudo().write({"milestone_id": milestone_id_val})

        if vals.get("parent_id") in self.ids:
            raise UserError(_("Sorry. You can't set a task as its parent task."))

        # step change: update date_last_status_change
        now = fields.Datetime.now()
        if "step_id" in vals:
            if "project_id" not in vals and self.filtered(lambda t: not t.project_id):
                raise UserError(
                    _("You can only set a personal stage on a private task.")
                )

            additional_vals.update(self.update_date_closed(vals["step_id"]))
            additional_vals["date_last_status_change"] = now
        task_ids_without_user_set = set()
        if "user_ids" in vals and "date_assign" not in vals:
            # prepare update of date_assign after super call
            task_ids_without_user_set = {task.id for task in self if not task.user_ids}

        # recurrence fields
        rec_fields = vals.keys() & self._get_recurrence_fields()
        if rec_fields:
            rec_values = {rec_field: vals[rec_field] for rec_field in rec_fields}
            for task in self:
                if task.recurrence_id:
                    task.recurrence_id.write(rec_values)
                elif vals.get("recurring_task"):
                    recurrence = self.env["project.task.recurrence"].create(rec_values)
                    task.recurrence_id = recurrence.id

        if not vals.get("recurring_task", True) and self.recurrence_id:
            tasks_in_recurrence = self.recurrence_id.task_ids
            self.recurrence_id.unlink()
            tasks_in_recurrence.write({"recurring_task": False})

        # Track user_ids to send assignment notifications
        old_user_ids = {t: t.user_ids for t in self.sudo()}

        if "triage_id" in vals and not vals["triage_id"]:
            del vals["triage_id"]

        # sends an email to the 'Task Creation' subtype subscribers
        # When project_id is changed
        project_link_per_task_id = {}
        if vals.get("project_id"):
            project = self.env["project.project"].browse(vals.get("project_id"))
            notification_subtype_id = self.env["ir.model.data"]._xmlid_to_res_id(
                "project.mt_project_task_new"
            )
            partner_ids = project.message_follower_ids.filtered(
                lambda follower: notification_subtype_id in follower.subtype_ids.ids
            ).partner_id.ids
            if partner_ids:
                link_per_project_id = {}
                for task in self:
                    if task.project_id:
                        project_link = link_per_project_id.get(task.project_id.id)
                        if not project_link:
                            project_link = link_per_project_id[task.project_id.id] = (
                                task.project_id._get_html_link(
                                    title=task.project_id.display_name
                                )
                            )
                        project_link_per_task_id[task.id] = project_link
        if vals.get("parent_id") is False:
            additional_vals["display_in_project"] = True
        if "description" in vals:
            # the portal user cannot access to html_field_history and so it would be
            # better to write in sudo for description field to avoid giving access to html_field_history
            additional_vals["description"] = vals.pop("description")

            # write changes
        if self.env.su or not self.env.user._is_portal():
            vals.update(additional_vals)
        elif additional_vals:
            super(ProjectTask, self.sudo()).write(additional_vals)
        result = super().write(vals)

        if "user_ids" in vals:
            self._populate_missing_triages()

        # user_ids change: update date_assign
        if "user_ids" in vals:
            for task in self.sudo():
                if not task.user_ids and task.date_assign:
                    task.date_assign = False
                elif "date_assign" not in vals and task.id in task_ids_without_user_set:
                    task.date_assign = now

        # rating on stage
        if "step_id" in vals and vals.get("step_id"):
            self.sudo().filtered(
                lambda x: x.step_id.rating_active and x.step_id.rating_status == "stage"
            )._send_task_rating_mail(force_send=True)

        if "state" in vals:
            # Stamp the status-change date once for the whole batch (single UPDATE)
            # rather than per record inside the loop below.
            self.sudo().date_last_status_change = now
            # specific use case: when the blocked task goes from 'forced' done state to a not closed state, we fix the state back to waiting
            if vals["state"] not in CLOSED_STATES and vals["state"] != "blocked":
                for task in self.sudo():
                    if task.allow_dependencies and task.is_blocked_by_predecessors():
                        task.state = "blocked"
        elif "project_id" in vals:
            # Re-homing a task into another project drops it onto that project's
            # default *non-folded* step (_compute_step_id → step_find fold=False).
            # State follows step in this model, so a closed state in an open step
            # is an invalid combination: reopen every non-blocked task —
            # done/canceled included — and clear its now-stale closure date so
            # deadline_met/_compute_elapsed don't read an undone completion.
            # _compute_state keeps genuinely predecessor-blocked tasks blocked.
            reopened = self.filtered(lambda t: t.state != "blocked")
            reopened.state = "in_progress"
            reopened.filtered("date_closed").date_closed = False

        # Do not recompute the state when changing the parent (to avoid resetting the state)
        if "parent_id" in vals:
            self.env.remove_to_compute(self._fields["state"], self)

        self._task_message_auto_subscribe_notify(
            {task: task.user_ids - old_user_ids[task] - self.env.user for task in self}
        )

        if partner_ids:
            for task in self:
                project_link = project_link_per_task_id.get(task.id)
                if project_link:
                    body = _(
                        "Task Transferred from Project %(source_project)s to %(destination_project)s",
                        source_project=project_link,
                        destination_project=task.project_id._get_html_link(
                            title=task.project_id.display_name
                        ),
                    )
                else:
                    body = _("Task Converted from To-Do")
                task.message_notify(
                    body=body,
                    partner_ids=partner_ids,
                    email_layout_xmlid="mail.mail_notification_layout",
                    notify_author_mention=False,
                )
        return result

    def unlink(self) -> bool:
        # Add subtasks to batch of tasks to delete
        self |= self._get_all_subtasks()
        last_task_id_per_recurrence_id = (
            self.recurrence_id._get_last_task_id_per_recurrence_id()
        )
        for task in self:
            if task.id == last_task_id_per_recurrence_id.get(task.recurrence_id.id):
                task.recurrence_id.unlink()
        return super().unlink()

    def update_date_closed(self, step_id: int) -> None:
        """Return dict setting date_closed when step is folded (task closed)."""
        step = self.env["project.workflow.step"].browse(step_id)
        if step.fold:
            return {"date_closed": fields.Datetime.now()}
        return {"date_closed": False}

    # ------------------------------------------------------------------
    # Resource reservation integration (contracts from resource.scheduling.mixin)
    # ------------------------------------------------------------------

    def _get_reservation_date_fields(self):
        """Return (start_field, end_field) names for reservation sync."""
        return ("planned_date_begin", "date_end")

    def _get_reservation_vals_list(self):
        """Build one reservation dict per assignee with a resolvable resource.

        Returns an empty list when the task has no scheduling dates, no
        assignees, or no assignee with a resource (e.g. portal users).

        Each assignee is rebound to their own ``company_id`` before the
        resource lookup.  ``user._get_project_task_resource`` walks
        ``user.employee_id``, which is a company-dependent related field;
        without the rebind, a user editing the task from a different
        active company would see every assignee's resource resolve to
        False and the sync would wipe the existing reservations.
        """
        self.ensure_one()
        start_field, end_field = self._get_reservation_date_fields()
        if not start_field or not end_field:
            return []
        date_start = self[start_field]
        date_end = self[end_field]
        if not date_start or not date_end:
            return []

        vals_list = []
        for user in self.user_ids:
            # The user→resource helper lives in ``project_enterprise``; in
            # core-only deployments no task carries reservations so skip.
            get_resource = getattr(user, "_get_project_task_resource", None)
            if not get_resource:
                continue
            scoped = user.with_company(user.company_id) if user.company_id else user
            resource = scoped._get_project_task_resource()
            if not resource:
                continue
            vals_list.append(
                {
                    "name": self.display_name,
                    "date_start": date_start,
                    "date_end": date_end,
                    "resource_id": resource.id,
                    "allocated_percentage": self.allocated_percentage or 100.0,
                    "enforcement_mode": "soft",
                }
            )
        return vals_list

    def _get_sync_trigger_fields(self):
        """Assignees and allocation changes also trigger a reservation sync."""
        triggers = super()._get_sync_trigger_fields()
        triggers |= {"user_ids", "allocated_percentage"}
        return triggers

    @api.onchange("date_end", "planned_date_begin")
    def _onchange_planned_dates(self):
        """Clear ``planned_date_begin`` when ``date_end`` is removed.

        Data invariant: a scheduled-start without a scheduled-end is a
        meaningless schedule.  Mirrors what users expect when they
        unschedule a task by clearing the deadline.
        """
        if not self.date_end:
            self.planned_date_begin = False

    def action_unschedule_task(self):
        """Clear scheduling dates (used by gantt 'unschedule' action)."""
        self.write(
            {
                "planned_date_begin": False,
                "date_end": False,
            }
        )

    @api.model
    def _calculate_planned_dates(
        self, date_start, date_stop, user_id=None, calendar=None
    ):
        """Snap a (start, stop) range to the first/last working intervals.

        Returns the input range unchanged when no calendar is resolvable
        or when the range falls entirely outside working time.  Used by
        ``project_enterprise`` for gantt drag-on-calendar UX, and
        available to any consumer that needs calendar-aware date alignment.
        """
        if not (date_start and date_stop):
            raise UserError(
                _(
                    "One parameter is missing to use this method. "
                    "You should give a start and end dates."
                )
            )
        start, stop = date_start, date_stop
        if isinstance(start, str):
            start = fields.Datetime.from_string(start)
        if isinstance(stop, str):
            stop = fields.Datetime.from_string(stop)

        if not calendar:
            user = (
                self.env["res.users"].sudo().browse(user_id)
                if user_id and user_id != self.env.user.id
                else self.env.user
            )
            calendar = (
                user.resource_calendar_id or self.env.company.resource_calendar_id
            )
            if not calendar:
                return date_start, date_stop

        if not start.tzinfo:
            start = start.replace(tzinfo=UTC)
        if not stop.tzinfo:
            stop = stop.replace(tzinfo=UTC)

        intervals = calendar._work_intervals_batch(start, stop)[False]
        if not intervals:
            return date_start, date_stop
        list_intervals = [(s, e) for s, e, _records in intervals]
        start = list_intervals[0][0].astimezone(UTC).replace(tzinfo=None)
        stop = list_intervals[-1][1].astimezone(UTC).replace(tzinfo=None)
        return start, stop

    def action_view_schedule(self):
        """Open the reservation view filtered to the assignees' resources.

        Shows every reservation held by each assignee (across all source
        models, not only this task) so the user can spot cross-task
        conflicts.  The calendar view opens on this task's scheduled
        start (or end) to save a scroll.
        """
        self.ensure_one()
        resources = self.env["resource.resource"]
        for user in self.user_ids:
            get_resource = getattr(user, "_get_project_task_resource", None)
            if get_resource:
                resource = get_resource()
                if resource:
                    resources |= resource

        if len(resources) == 1:
            action_name = self.env._("Schedule — %s", resources.name)
        elif resources:
            action_name = self.env._("Schedule — %s assignees", len(resources))
        else:
            action_name = self.env._("Schedule")

        context = {"search_default_my_schedule": 0}
        start_field, end_field = self._get_reservation_date_fields()
        anchor = (start_field and self[start_field]) or (end_field and self[end_field])
        if anchor:
            context["initial_date"] = anchor

        return {
            "type": "ir.actions.act_window",
            "name": action_name,
            "res_model": "resource.reservation",
            "view_mode": "calendar,list,form",
            "domain": [("resource_id", "in", resources.ids)],
            "context": context,
        }

    def _search_on_comodel(
        self,
        domain: list,
        field: str,
        comodel: str,
        additional_domain: list | None = None,
    ) -> list | bool:
        """This method is called by `group_expand` methods, whose purpose is to add empty groups to the `read_group`
        (which otherwise returns groups containing records that match the domain).
        When specifically filtering on a comodel's field, the result of the `read_group` should contain all matching groups.
        However, if the search isn't filtered on any comodel's field, the result shouldn't be affected,
        which explains why we return `False` if `filtered_domain` is empty.

        Returns:
            False or recordset of the comodel given in parameter.

        """

        def _change_operator(domain) -> str:
            new_domain = []
            for dom in domain:
                if len(dom) == 3:
                    _, op, value = dom
                    if op in ("any", "not any"):
                        new_op = "in" if op == "any" else "not in"
                        ids = [
                            val[2]
                            for val in value
                            if isinstance(val, (tuple, list))
                            and isinstance(val[2], int)
                        ]
                        new_domain.append(("id", new_op, ids))
                        continue
                    op = "ilike" if op == "child_of" else op
                    if isinstance(value, list) and all(
                        isinstance(val, int) for val in value
                    ):
                        new_domain.append(("id", op, value))
                    elif isinstance(value, str) or (
                        isinstance(value, list)
                        and not all(isinstance(val, str) for val in value)
                    ):
                        new_domain.append(("name", op, value))
                    if isinstance(value, int):
                        if op == "=":
                            op = "in"
                        if op == "!=":
                            op = "not in"
                        new_domain.append(("id", op, [value]))
                else:
                    new_domain.append(dom)
            return Domain(new_domain)

        filtered_domain = filter_domain_leaf(
            domain,
            lambda field_to_check: (
                field_to_check
                in [
                    field,
                    f"{field}.id",
                    f"{field}.name",
                ]
            ),
            {
                field: "name",
                f"{field}.id": "id",
                f"{field}.name": "name",
            },
        )
        if filtered_domain.is_true():
            return self.env[comodel]
        filtered_domain = _change_operator(filtered_domain)
        if additional_domain:
            filtered_domain &= Domain(additional_domain)
        return self.env[comodel].search(filtered_domain)

    # ---------------------------------------------------
    # Subtasks
    # ---------------------------------------------------

    @api.depends("parent_id.partner_id", "project_id", "project_id.partner_id")
    def _compute_partner_id(self) -> None:
        """Compute the partner_id when the tasks have no partner_id.

        Use the project partner_id if any, or else the parent task partner_id.
        """
        for task in self:
            if task.has_template_ancestor:
                continue
            if task.partner_id and not (task.project_id or task.parent_id):
                task.partner_id = False
                continue
            if not task.partner_id:
                task.partner_id = self._get_default_partner_id(
                    task.project_id, task.parent_id
                )

    @api.depends("project_id")
    def _compute_milestone_id(self) -> None:
        for task in self:
            if task.project_id != task.milestone_id.project_id:
                task.milestone_id = (
                    task.parent_id.project_id == task.project_id
                    and task.parent_id.milestone_id
                )

    def _compute_has_late_and_unreached_milestone(self) -> None:
        if all(not task.allow_milestones for task in self):
            self.has_late_and_unreached_milestone = False
            return
        late_milestones = (
            self.env["project.milestone"]
            .sudo()
            ._search(
                [  # sudo is needed for the portal user in Project Sharing.
                    ("id", "in", self.milestone_id.ids),
                    ("is_reached", "=", False),
                    # Strictly before today, matching the search method below
                    # (a milestone due *today* is not yet late).
                    ("deadline", "<", fields.Date.today()),
                ]
            )
        )
        for task in self:
            task.has_late_and_unreached_milestone = (
                task.allow_milestones and task.milestone_id.id in late_milestones
            )

    def _search_has_late_and_unreached_milestone(
        self, operator: str, value: Any
    ) -> list:
        if operator != "in":
            return NotImplemented
        return [
            ("allow_milestones", "=", True),
            (
                "milestone_id",
                "any",
                [
                    ("is_reached", "=", False),
                    ("deadline", "<", fields.Date.today()),
                ],
            ),
        ]

    # ---------------------------------------------------
    # Mail gateway
    # ---------------------------------------------------

    def _notify_by_email_prepare_rendering_context(
        self,
        message: Any,
        msg_vals: dict | bool = False,
        model_description: str | bool = False,
        force_email_company: Any = False,
        force_email_lang: str | bool = False,
        force_record_name: str | bool = False,
    ) -> dict:
        render_context = super()._notify_by_email_prepare_rendering_context(
            message,
            msg_vals=msg_vals,
            model_description=model_description,
            force_email_company=force_email_company,
            force_email_lang=force_email_lang,
            force_record_name=force_record_name,
        )
        project_name = self.project_id.sudo().name
        stage_name = self.step_id.name
        subtitles = ""
        if project_name and stage_name:
            subtitles = _(
                "Project: %(project_name)s, Stage: %(stage_name)s",
                project_name=project_name,
                stage_name=stage_name,
            )
        elif project_name:
            subtitles = _("Project: %(project_name)s", project_name=project_name)
        elif stage_name:
            subtitles = _("Stage: %(stage_name)s", stage_name=stage_name)
        if subtitles:
            render_context["subtitles"].append(subtitles)
        return render_context

    def _send_email_notify_to_cc(self, partners_to_notify: Self) -> None:
        # TDE TODO: this should be removed with email-like recipients management
        self.ensure_one()
        template_id = self.env["ir.model.data"]._xmlid_to_res_id(
            "project.task_invitation_follower", raise_if_not_found=False
        )
        if not template_id:
            return
        task_model_description = self.env["ir.model"]._get(self._name).display_name
        values = {
            "object": self,
        }
        for partner in partners_to_notify:
            values["partner_name"] = partner.name
            assignation_msg = self.env["ir.qweb"]._render(
                "project.task_invitation_follower",
                values,
                minimal_qcontext=True,
            )
            self.message_notify(
                subject=_("You have been invited to follow %s", self.display_name),
                body=assignation_msg,
                partner_ids=partner.ids,
                email_layout_xmlid="mail.mail_notification_layout",
                model_description=task_model_description,
                mail_auto_delete=True,
            )

    @api.model
    def _task_message_auto_subscribe_notify(self, users_per_task: dict) -> None:
        if self.env.context.get("mail_auto_subscribe_no_notify"):
            return
        # Utility method to send assignation notification upon writing/creation.
        template_id = self.env["ir.model.data"]._xmlid_to_res_id(
            "project.project_message_user_assigned", raise_if_not_found=False
        )
        if not template_id:
            return
        task_model_description = self.env["ir.model"]._get(self._name).display_name
        for task, users in users_per_task.items():
            if not users:
                continue
            values = {
                "object": task,
                "model_description": task_model_description,
                "access_link": task._notify_get_action_link("view"),
            }
            for user in users:
                values.update(assignee_name=user.sudo().name)
                assignation_msg = self.env["ir.qweb"]._render(
                    "project.project_message_user_assigned",
                    values,
                    minimal_qcontext=True,
                )
                assignation_msg = self.env["mail.render.mixin"]._replace_local_links(
                    assignation_msg
                )
                task.message_notify(
                    subject=_("You have been assigned to %s", task.display_name),
                    body=assignation_msg,
                    partner_ids=user.partner_id.ids,
                    email_layout_xmlid="mail.mail_notification_layout",
                    model_description=task_model_description,
                    mail_auto_delete=True,
                )

    def _message_auto_subscribe_followers(
        self, updated_values: dict[str, Any], default_subtype_ids: list[int]
    ) -> list:
        if "user_ids" not in updated_values:
            return []
        # Since the changes to user_ids becoming a m2m, the default implementation of this function
        #  could not work anymore, override the function to keep the functionality.
        new_followers = []
        # Normalize input to tuple of ids
        value = self._fields["user_ids"].convert_to_cache(
            updated_values.get("user_ids", []),
            self.env["project.task"],
            validate=False,
        )
        users = self.env["res.users"].browse(value)
        for user in users:
            try:
                if user.partner_id:
                    # The you have been assigned notification is handled separately
                    new_followers.append(
                        (user.partner_id.id, default_subtype_ids, False)
                    )
            except Exception:
                _logger.debug(
                    "Failed to collect follower for user %s",
                    user.id,
                    exc_info=True,
                )
        return new_followers

    def _track_template(self, changes: dict[str, Any]) -> dict:
        res = super()._track_template(changes)
        test_task = self[0]
        if (
            "step_id" in changes
            and test_task.step_id.mail_template_id
            and not test_task.is_template
        ):
            res["step_id"] = (
                test_task.step_id.mail_template_id,
                {
                    "auto_delete_keep_log": False,
                    "subtype_id": self.env["ir.model.data"]._xmlid_to_res_id(
                        "mail.mt_note"
                    ),
                    "email_layout_xmlid": "mail.mail_notification_light",
                },
            )
        return res

    def _creation_subtype(self) -> Self:
        return self.env.ref("project.mt_task_new")

    def _creation_message(self) -> str:
        self.ensure_one()
        if self.project_id:
            return _(
                'A new task has been created in the "%(project_name)s" project.',
                project_name=self.project_id.display_name,
            )
        return _("A new task has been created and is not part of any project.")

    def _track_subtype(self, init_values: dict[str, Any]) -> Self:
        self.ensure_one()
        mail_message_subtype_per_state = {
            "done": "project.mt_task_done",
            "canceled": "project.mt_task_canceled",
            "in_progress": "project.mt_task_in_progress",
            "approved": "project.mt_task_approved",
            "changes_requested": "project.mt_task_changes_requested",
            "blocked": "project.mt_task_waiting",
        }

        if "step_id" in init_values:
            return self.env.ref("project.mt_task_stage")
        elif "state" in init_values and self.state in mail_message_subtype_per_state:
            return self.env.ref(mail_message_subtype_per_state[self.state])
        return super()._track_subtype(init_values)

    def _mail_get_message_subtypes(self) -> Self:
        res = super()._mail_get_message_subtypes()
        if not self.step_id.rating_active:
            res -= self.env.ref("project.mt_task_rating")
        if len(self) == 1:
            waiting_subtype = self.env.ref("project.mt_task_waiting")
            if (
                (self.project_id and not self.project_id.allow_dependencies)
                or (
                    not self.project_id
                    and not self.env.user.has_group(
                        "project.group_project_task_dependencies"
                    )
                )
            ) and waiting_subtype in res:
                res -= waiting_subtype
        return res

    def _notify_get_recipients_groups(
        self,
        message: Any,
        model_description: str,
        msg_vals: dict | bool = False,
    ) -> list:
        # Handle project users and managers recipients that can assign
        # tasks and create new one directly from notification emails. Also give
        # access button to portal users and portal customers. If they are notified
        # they should probably have access to the document.
        groups = super()._notify_get_recipients_groups(
            message, model_description, msg_vals=msg_vals
        )
        if not self:
            return groups

        self.ensure_one()

        project_user_group_id = self.env.ref("project.group_project_user").id
        new_group = (
            "group_project_user",
            lambda pdata: (
                pdata["type"] == "user" and project_user_group_id in pdata["groups"]
            ),
            {},
        )
        groups = [new_group] + groups

        if self.project_privacy_visibility in ["invited_users", "portal"]:
            groups.insert(
                0,
                (
                    "allowed_portal_users",
                    lambda pdata: pdata["type"] in ["invited_users", "portal"],
                    {
                        "active": True,
                        "has_button_access": True,
                    },
                ),
            )
        portal_privacy = self.project_id.privacy_visibility in [
            "invited_users",
            "portal",
        ]
        for group_name, _group_method, group_data in groups:
            if group_name in ("customer", "user") or (
                group_name == "portal_customer" and not portal_privacy
            ):
                group_data["has_button_access"] = False
            elif group_name == "portal_customer" and portal_privacy:
                group_data["has_button_access"] = True

        return groups

    def _notify_get_reply_to(
        self, default: str | None = None, author_id: int | bool = False
    ) -> dict:
        # Override to set alias of tasks to their project if any
        aliases = (
            self.sudo()
            .mapped("project_id")
            ._notify_get_reply_to(default=default, author_id=author_id)
        )
        res = {task.id: aliases.get(task.project_id.id) for task in self}
        leftover = self.filtered(lambda rec: not rec.project_id)
        if leftover:
            res.update(
                super(ProjectTask, leftover)._notify_get_reply_to(
                    default=default, author_id=author_id
                )
            )
        return res

    def _find_internal_users_from_address_mail(
        self, emails: list[str], project_id: int | bool = False
    ) -> Self:
        sanitized_email_dict = self._mail_cc_sanitized_raw_dict(emails)
        matched_partners = self.env["res.partner"]._find_or_create_from_emails(
            sanitized_email_dict.keys(), no_create=True
        )
        partners = self.env["res.partner"].concat(*matched_partners)
        unresolved_emails = set(sanitized_email_dict) - set(partners.mapped("email"))
        if project_id:
            project = self.env["project.project"].browse(project_id)
            project_alias_address = (
                project.alias_name + "@" + project.alias_domain_id.name
            )
            # Removing project alias from unresolved_emails as this will be added to cc_mail address and when
            # a mail is sent unnecessary partner is created in the name of project_alias
            unresolved_emails.discard(project_alias_address)
        unmatched_partner_emails = [
            sanitized_email_dict.get(email) for email in unresolved_emails
        ]

        users = partners.user_ids
        internal_user_ids = users.filtered(lambda u: not u.share).ids

        partner_emails_without_internal_users = (partners - users.partner_id).mapped(
            "email_formatted"
        )

        return (
            internal_user_ids,
            partner_emails_without_internal_users,
            unmatched_partner_emails,
        )

    @api.model
    def message_new(
        self,
        msg_dict: dict[str, Any],
        custom_values: dict[str, Any] | None = None,
    ) -> Self:
        # remove default author when going through the mail gateway. Indeed we
        # do not want to explicitly set user_id to False; however we do not
        # want the gateway user to be responsible if no other responsible is
        # found.
        create_context = dict(self.env.context or {})
        create_context["default_user_ids"] = False
        if custom_values is None:
            custom_values = {}
        # Auto create partner if not existent when the task is created from email
        if not msg_dict.get("author_id") and msg_dict.get("email_from"):
            author = self.env["mail.thread"]._partner_find_from_emails_single(
                [msg_dict["email_from"]], no_create=False
            )
            msg_dict["author_id"] = author.id

        defaults = {
            "name": msg_dict.get("subject") or _("No Subject"),
            "allocated_hours": 0.0,
            "partner_id": msg_dict.get("author_id"),
            "email_cc": (
                ", ".join(self._mail_cc_sanitized_raw_dict(msg_dict.get("cc")).values())
                if custom_values.get("project_id")
                else ""
            ),
        }
        defaults.update(custom_values)

        # users having email address matched from emails recepients are filtered out and added as assignees to the task
        if msg_dict.get("to"):
            (
                internal_users,
                partner_emails_without_users,
                unmatched_partner_emails,
            ) = self._find_internal_users_from_address_mail(
                msg_dict.get("to"), defaults.get("project_id")
            )
            # set only internal users as assignees
            defaults["user_ids"] = defaults.get("user_ids", []) + internal_users
            if custom_values.get("project_id") and (
                partner_emails_without_users or unmatched_partner_emails
            ):
                defaults["email_cc"] = (
                    defaults.get("email_cc", "")
                    + ", "
                    + ", ".join(partner_emails_without_users + unmatched_partner_emails)
                )
        task = super(ProjectTask, self.with_context(create_context)).message_new(
            msg_dict, custom_values=defaults
        )
        partners = task._partner_find_from_emails_single(
            tools.email_split(
                (msg_dict.get("to") or "") + "," + (msg_dict.get("cc") or "")
            ),
            no_create=True,
        )
        if task.project_id:
            task.message_subscribe(partners.ids)
        return task

    def message_update(
        self,
        msg_dict: dict[str, Any],
        update_vals: dict[str, Any] | None = None,
    ) -> bool:
        for task in self:
            partners = task._partner_find_from_emails_single(
                tools.email_split(
                    (msg_dict.get("to") or "") + "," + (msg_dict.get("cc") or "")
                ),
                no_create=True,
            )
            task.message_subscribe(partners.ids)
        return super().message_update(msg_dict, update_vals=update_vals)

    def _notify_by_email_get_headers(self, headers=None) -> dict:
        headers = super()._notify_by_email_get_headers(headers=headers)
        if self.project_id:
            current_objects = [
                h for h in headers.get("X-Odoo-Objects", "").split(",") if h
            ]
            current_objects.insert(0, "project.project-%s, " % self.project_id.id)
            headers["X-Odoo-Objects"] = ",".join(current_objects)
        if self.tag_ids:
            headers["X-Odoo-Tags"] = ",".join(self.tag_ids.mapped("name"))
        return headers

    def _message_post_after_hook(self, message: Any, msg_vals: dict[str, Any]) -> None:
        if message.attachment_ids and not self.displayed_image_id:
            image_attachments = message.attachment_ids.filtered(
                lambda a: a.mimetype and a.mimetype.startswith("image/")
            )
            if image_attachments:
                self.displayed_image_id = image_attachments[0]

        # use the sanitized body of the email from the message thread to populate the task's description
        if (
            not self.description
            and message.subtype_id == self._creation_subtype()
            and self.partner_id == message.author_id
            and msg_vals["message_type"] == "email"
            and msg_vals.get("body")
        ):
            # Remove the signature from the email body
            source_html = msg_vals.get("body")
            doc = html.fromstring(source_html)

            signature_xpath = '//*[@id="Signature"] | //*[@data-smartmail="gmail_signature"] | //span[normalize-space(.) = "--"]'

            for element in doc.xpath(signature_xpath):
                element.getparent().remove(element)

            cleaned_html = html.tostring(doc, encoding="unicode").strip()
            self.description = html_sanitize(cleaned_html)

        return super()._message_post_after_hook(message, msg_vals)

    def _get_projects_to_make_billable_domain(self, additional_domain=None) -> list:
        return Domain("partner_id", "!=", False) & Domain(
            additional_domain or Domain.TRUE
        )

    def _get_all_subtasks(self) -> Self:
        return self.browse(
            set.union(set(), *self._get_subtask_ids_per_task_id().values())
        )

    def _get_subtask_ids_per_task_id(self) -> dict:
        if not self:
            return {}

        res = {id_: [] for id_ in self._ids}
        if all(self._ids):
            self.env.cr.execute(
                """
         WITH RECURSIVE task_tree
                     AS (
                     SELECT id, id as supertask_id
                       FROM project_task
                      WHERE id = ANY(%(ancestor_ids)s)
                      UNION
                         SELECT t.id, tree.supertask_id
                           FROM project_task t
                           JOIN task_tree tree
                             ON tree.id = t.parent_id
                            AND t.active in (TRUE, %(active)s)
                          WHERE t.parent_id IS NOT NULL
               ) SELECT supertask_id, ARRAY_AGG(id)
                   FROM task_tree
                  WHERE id != supertask_id
               GROUP BY supertask_id
                """,
                {
                    "ancestor_ids": list(self.ids),
                    "active": self.env.context.get("active_test", True),
                },
            )
            res.update(dict(self.env.cr.fetchall()))
        else:
            res.update({task.id: task._get_subtasks_recursively().ids for task in self})
        return res

    def _get_subtasks_recursively(self) -> Self:
        children = self.child_ids
        if not children:
            return self.env["project.task"]
        return children + children._get_subtasks_recursively()

    def action_open_parent_task(self) -> dict:
        return {
            "name": _("Parent Task"),
            "view_mode": "form",
            "res_model": "project.task",
            "res_id": self.parent_id.id,
            "type": "ir.actions.act_window",
            "context": self.env.context,
        }

    def action_project_sharing_view_parent_task(self) -> dict:
        if self.parent_id.project_id != self.project_id and self.env.user._is_portal():
            project = self.parent_id.project_id._filtered_access("read")
            if project:
                url = f"/my/projects/{self.parent_id.project_id.id}/task/{self.parent_id.id}"
                if project._check_project_sharing_access():
                    url = f"/my/projects/{self.parent_id.project_id.id}?task_id={self.parent_id.id}"
                return {
                    "name": "Portal Parent Task",
                    "type": "ir.actions.act_url",
                    "url": url,
                }
            elif self.display_parent_task_button:
                return self.parent_id.get_portal_url()
            # The portal user has no access to the parent task, so normally the button should be invisible.
            return {}
        action = self.with_context(
            {
                "search_view_ref": "project.project_sharing_project_task_view_search",
            }
        ).action_open_parent_task()
        action["views"] = [
            (
                self.env.ref("project.project_sharing_project_task_view_form").id,
                "form",
            )
        ]
        action["search_view_id"] = self.env.ref(
            "project.project_sharing_project_task_view_search"
        ).id
        return action

    # ------------
    # Actions
    # ------------

    def action_open_task(self) -> dict:
        return {
            "view_mode": "form",
            "res_model": "project.task",
            "res_id": self.id,
            "type": "ir.actions.act_window",
            "context": self.env.context,
        }

    def action_project_sharing_open_task(self) -> dict:
        action = self.action_open_task()
        action["views"] = [
            [
                self.env.ref("project.project_sharing_project_task_view_form").id,
                "form",
            ]
        ]
        return action

    def action_project_sharing_open_subtasks(self) -> dict:
        self.ensure_one()
        subtasks = self.env["project.task"].search(
            [("id", "child_of", self.id), ("id", "!=", self.id)]
        )
        if subtasks.project_id == self.project_id:
            action = self.env["ir.actions.act_window"]._for_xml_id(
                "project.project_sharing_project_task_action_sub_task"
            )
            if len(subtasks) == 1:
                action["view_mode"] = "form"
                action["views"] = [
                    (view_id, view_type)
                    for view_id, view_type in action["views"]
                    if view_type == "form"
                ]
                action["res_id"] = subtasks.id
            return action
        return {
            "name": "Portal Sub-tasks",
            "type": "ir.actions.act_url",
            "url": (
                f"/my/projects/{self.project_id.id}/task/{self.id}/subtasks"
                if len(subtasks) > 1
                else subtasks.get_portal_url(query_string="project_sharing=1")
            ),
        }

    def action_project_sharing_open_blocking(self) -> dict:
        self.ensure_one()
        blockings = self.successor_ids
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "project.project_sharing_project_task_action_blocking_tasks"
        )
        if len(blockings) == 1:
            action["view_mode"] = "form"
            action["views"] = [
                (view_id, view_type)
                for view_id, view_type in action["views"]
                if view_type == "form"
            ]
            action["res_id"] = blockings.id
        return action

    def action_dependent_tasks(self) -> dict:
        self.ensure_one()
        return {
            "res_model": "project.task",
            "type": "ir.actions.act_window",
            "context": {
                **self.env.context,
                "default_predecessor_ids": [Command.link(self.id)],
                "show_project_update": False,
                "search_default_open_tasks": True,
            },
            "domain": [("predecessor_ids", "=", self.id)],
            "name": _("Dependent Tasks"),
            "view_mode": "list,form,kanban,calendar,pivot,graph,activity",
        }

    def action_recurring_tasks(self) -> dict:
        return {
            "name": _("Tasks in Recurrence"),
            "type": "ir.actions.act_window",
            "res_model": "project.task",
            "view_mode": "list,form,kanban,calendar,pivot,graph,activity",
            "context": {"create": False},
            "domain": [("recurrence_id", "in", self.recurrence_id.ids)],
        }

    def action_project_sharing_recurring_tasks(self) -> dict:
        self.ensure_one()
        recurrent_tasks = self.env["project.task"].search(
            [("recurrence_id", "in", self.recurrence_id.ids)]
        )
        # If all the recurrent tasks are in the same project, open the list view in sharing mode.
        if recurrent_tasks.project_id == self.project_id:
            action = self.env["ir.actions.act_window"]._for_xml_id(
                "project.project_sharing_project_task_recurring_tasks_action"
            )
            action.update(
                {
                    "context": {"default_project_id": self.project_id.id},
                    "domain": [
                        ("project_id", "=", self.project_id.id),
                        ("recurrence_id", "in", self.recurrence_id.ids),
                    ],
                }
            )
            return action
        # If at least one recurrent task belong to another project, open the portal page
        return {
            "name": "Portal Recurrent Tasks",
            "type": "ir.actions.act_url",
            "url": f"/my/projects/{self.project_id.id}/task/{self.id}/recurrent_tasks",
        }

    def action_open_ratings(self) -> dict:
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "project.rating_rating_action_task"
        )
        if self.rating_count == 1:
            action["view_mode"] = "form"
            action["res_id"] = self.rating_ids[0].id
            action["views"] = [
                [
                    self.env.ref("project.rating_rating_view_form_project").id,
                    "form",
                ]
            ]
            return action
        else:
            return action

    def action_unlink_recurrence(self) -> None:
        self.recurrence_id.task_ids.recurring_task = False
        self.recurrence_id.unlink()

    def action_convert_to_subtask(self) -> dict | bool:
        self.ensure_one()
        if self.project_id:
            return {
                "name": _("Convert to Task/Sub-Task"),
                "type": "ir.actions.act_window",
                "res_model": "project.task",
                "res_id": self.id,
                "views": [
                    (
                        self.env.ref(
                            "project.project_task_convert_to_subtask_view_form",
                            False,
                        ).id,
                        "form",
                    )
                ],
                "target": "new",
            }
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "danger",
                "message": _(
                    "Private tasks cannot be converted into sub-tasks. Please set a project on the task to gain access to this feature."
                ),
            },
        }

    def action_convert_to_template(self) -> None:
        self.ensure_one()
        if not self.project_id:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "type": "danger",
                    "message": _("Private tasks cannot be converted into templates"),
                },
            }
        if self.is_template:
            return {
                "type": "ir.actions.client",
                "tag": "project_show_template_undo_confirmation_dialog",
                "params": {
                    "task_id": self.id,
                },
            }
        self.is_template = True
        self.role_ids = False
        self.message_post(body=_("Task converted to template"))
        return {
            "type": "ir.actions.client",
            "tag": "project_show_template_notification",
            "params": {
                "task_id": self.id,
                "next": {
                    "type": "ir.actions.client",
                    "tag": "soft_reload",
                },
            },
        }

    def action_undo_convert_to_template(self) -> None:
        self.ensure_one()
        self.is_template = False
        self.message_post(body=_("Template converted back to regular task"))
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "message": _("Template converted back to regular task"),
                "next": {
                    "type": "ir.actions.client",
                    "tag": "soft_reload",
                },
            },
        }

    def plan_task_in_calendar(self, vals: dict[str, Any]) -> dict:
        self.ensure_one()
        return self.write(vals)

    @api.model
    def _get_template_default_context_whitelist(self) -> set[str]:
        """Whitelist of fields that can be set through the `default_` context keys when creating a task from a template."""
        return [
            "parent_id",
        ]

    @api.model
    def _get_template_field_blacklist(self) -> set[str]:
        """Blacklist of fields to not copy when creating a task from a template."""
        return [
            "partner_id",
        ]

    def action_create_from_template(self, values=None) -> dict:
        self.ensure_one()
        values = values or {}
        default = (
            {
                key[8:]: value
                for key, value in self.env.context.items()
                if key.startswith("default_")
                and key[8:] in self._get_template_default_context_whitelist()
            }
            | dict.fromkeys(self._get_template_field_blacklist(), False)
            | values
        )
        return self.with_context(copy_from_template=True).copy(default=default).id

    def action_archive(self) -> dict | bool:
        child_tasks = self.child_ids.filtered(
            lambda child_task: not child_task.display_in_project
        )
        if child_tasks:
            child_tasks.action_archive()
        return super().action_archive()

    def _get_access_action(self, access_uid=None, force_website=False):
        self.ensure_one()
        user = (
            self.env["res.users"].sudo().browse(access_uid)
            if access_uid
            else self.env.user
        )
        if (
            user
            and user._is_portal()
            and self.with_user(user).has_access("read")
            and self.project_id
            and self.project_id.with_user(user).has_access("read")
            and self.project_id._check_project_sharing_access()
        ):
            return {
                "type": "ir.actions.act_url",
                "url": f"/my/projects/{self.project_id.id}/project_sharing/{self.id}",
                "target": "self",
            }
        return super()._get_access_action(access_uid, force_website)

    # ---------------------------------------------------
    # Rating business
    # ---------------------------------------------------

    def _send_task_rating_mail(self, force_send=False) -> None:
        for task in self:
            rating_template = task.step_id.rating_template_id
            partner = task.partner_id
            if (
                rating_template
                and partner
                and partner != self.env.user.partner_id
                and not task.is_template
            ):
                task.rating_send_request(
                    rating_template,
                    lang=task.partner_id.lang,
                    force_send=force_send,
                )

    def _rating_get_partner(self) -> Self:
        res = super()._rating_get_partner()
        if not res and self.project_id.partner_id:
            return self.project_id.partner_id
        return res

    def rating_apply(
        self,
        rate,
        token=None,
        rating=None,
        feedback=None,
        subtype_xmlid=None,
        notify_delay_send=False,
    ) -> Self:
        rating = super().rating_apply(
            rate,
            token=token,
            rating=rating,
            feedback=feedback,
            subtype_xmlid=subtype_xmlid,
            notify_delay_send=notify_delay_send,
        )
        if self.step_id and self.step_id.auto_update_state:
            state = (
                "approved"
                if rating.rating >= rating_data.RATING_LIMIT_SATISFIED
                else "changes_requested"
            )
            self.write({"state": state})
        return rating

    def _rating_apply_get_default_subtype_id(self) -> Self:
        return self.env["ir.model.data"]._xmlid_to_res_id("project.mt_task_rating")

    def _rating_get_parent_field_name(self) -> str:
        return "project_id"

    def _rating_get_operator(self) -> Self:
        """Overwrite since we have user_ids and not user_id"""
        tasks_with_one_user = self.filtered(
            lambda task: len(task.user_ids) == 1 and task.user_ids.partner_id
        )
        return tasks_with_one_user.user_ids.partner_id or self.env["res.partner"]

    # ---------------------------------------------------
    # Privacy
    # ---------------------------------------------------
    def _unsubscribe_portal_users(self) -> None:
        self.message_unsubscribe(
            partner_ids=self.message_partner_ids.filtered("user_ids.share").ids
        )

    @api.model
    def get_unusual_days(self, date_from: str, date_to: str | None = None) -> dict:
        calendar = self.env.company.resource_calendar_id
        return calendar._get_unusual_days(
            datetime.combine(fields.Date.from_string(date_from), time.min).replace(
                tzinfo=UTC
            ),
            datetime.combine(fields.Date.from_string(date_to), time.max).replace(
                tzinfo=UTC
            ),
        )

    def action_redirect_to_project_task_form(self) -> dict:
        menu_id = self.env.ref("project.menu_project_management_all_tasks").id
        return {
            "type": "ir.actions.act_url",
            "url": f"/odoo/{self.project_id.id}/action-project.act_project_project_2_project_task_all/{self.id}?menu_id={menu_id}",
            "target": "new",
        }

    @api.model
    def _read_group(
        self,
        domain,
        groupby=(),
        aggregates=(),
        having=(),
        offset=0,
        limit=None,
        order=None,
    ) -> list[tuple]:
        # A _read_group cannot be performed if records are grouped by triage_id
        # as it is a computed field. triage_ids behaves like a M2O from the point
        # of view of the user, we therefore use this field instead.
        if "triage_id" in groupby:
            # limitation: problem when both triage_id and triage_ids
            # appear in read_group, but this has no functional utility
            groupby = [
                ("triage_ids" if fname == "triage_id" else fname) for fname in groupby
            ]
            if order:
                # Word-boundary replace so an order already referencing
                # "triage_ids" isn't mangled into "triage_idss" (\b does not
                # match between the 'd' and 's' of the plural form).
                order = re.sub(r"\btriage_id\b", "triage_ids", order)
        return super()._read_group(
            domain, groupby, aggregates, having, offset, limit, order
        )

    # ---------------------------------------------------
    # Project Sharing
    # ---------------------------------------------------

    def project_sharing_toggle_is_follower(self) -> None:
        self.ensure_one()
        self.check_access("write")
        is_follower = self.message_is_follower
        if is_follower:
            self.sudo().message_unsubscribe(self.env.user.partner_id.ids)
        else:
            self.sudo().message_subscribe(self.env.user.partner_id.ids)
        return not is_follower

    @api.depends("subtask_count", "closed_subtask_count")
    def _compute_subtask_completion_percentage(self) -> None:
        for task in self:
            task.subtask_completion_percentage = (
                task.subtask_count and task.closed_subtask_count / task.subtask_count
            )

    @api.model
    def _get_allowed_access_params(self) -> set[str]:
        return super()._get_allowed_access_params() | {"project_sharing_id"}

    @api.model
    def _get_thread_with_access(
        self, thread_id, *, project_sharing_id=None, token=None, **kwargs
    ) -> Self:
        if project_sharing_id:
            if (
                result_token
                := ProjectSharingChatter._check_project_access_and_get_token(
                    self, project_sharing_id, self._name, thread_id, token
                )
            ):
                token = result_token
        return super()._get_thread_with_access(
            thread_id,
            project_sharing_id=project_sharing_id,
            token=token,
            **kwargs,
        )

    def get_mention_suggestions(self, search: str, limit: int = 8) -> list:
        """Return the 'limit'-first followers of the given task or followers of its project matching
        a 'search' string as a list of partner data (returned by `_to_store()`).
        See similar method for all partners `get_mention_suggestions()`.
        """
        self.ensure_one()
        project = self.project_id
        if not (
            project
            and project._check_project_sharing_access()
            and project._get_thread_with_access(project.id)
        ):
            return {}
        # sudo: mail.followers - reading message_follower_ids on accessible task/project is allowed
        followers = (
            project.sudo().message_follower_ids | self.sudo().message_follower_ids
        )
        domain = Domain(
            self.env["res.partner"]._get_mention_suggestions_domain(search)
        ) & Domain("id", "in", followers.partner_id.ids)
        partners = (
            self.env["res.partner"].sudo()._search_mention_suggestions(domain, limit)
        )
        return (
            Store()
            .add(
                partners,
                [
                    "email",
                    "im_status",
                    "name",
                    *partners._get_store_mention_fields(),
                ],
            )
            .get_result()
        )

    @api.model
    def get_import_templates(self) -> dict:
        return [
            {
                "label": _("Import Template for Tasks"),
                "template": "/project/static/xls/tasks_import_template.xlsx",
            }
        ]

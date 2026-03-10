from odoo import _, api, fields, models
from odoo.exceptions import UserError


class AutomationRuntime(models.Model):
    """Per-execution instance for automation workflow runs.

    Each time an automation's ``on_hand`` trigger fires (and the automation
    has multi-step DAG structure), one ``automation.runtime`` record is
    created to track isolated execution state across all steps.

    Unlike ``ir.actions.server.action_state`` (which is global and broken
    under concurrent runs), every field on this model and its child
    ``automation.runtime.line`` records is strictly per-execution. Two
    concurrent runs of the same automation never share state.

    ``automation_id`` accepts any ``base.automation`` rule regardless of
    its target model. The ``res_model``/``res_id`` fields record which
    specific business record is being automated.
    """

    _name = "automation.runtime"
    _description = "Automation Workflow Runtime Instance"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _check_company_auto = True
    _order = "create_date desc, id desc"

    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
        readonly=True,
        index=True,
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        string="Currency",
        required=True,
        default=lambda self: self.env.company.currency_id,
    )
    multicompany_id = fields.Many2one(
        comodel_name="res.company",
        string="Target Company",
        help="Target company for multi-company operations",
    )
    automation_id = fields.Many2one(
        comodel_name="base.automation",
        string="Automation",
        required=True,
        index=True,
        tracking=True,
        ondelete="restrict",
        help="The automation workflow definition being executed",
    )
    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Partner",
        domain=["|", ("parent_id", "=", False), ("is_company", "=", True)],
        index=True,
        tracking=True,
        help="Main partner for this operation (optional)",
    )
    diff_partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Alternative Partner",
        domain=["|", ("parent_id", "=", False), ("is_company", "=", True)],
        help="Alternative partner for specific actions in workflow",
    )
    # Target record for general automations (non-meta-workflow use)
    res_model = fields.Char(
        string="Target Model",
        index=True,
        help="Model of the record being automated (e.g. 'res.partner')",
    )
    res_id = fields.Integer(
        string="Target Record ID",
        index=True,
        help="ID of the specific record being automated",
    )
    name = fields.Char(
        string="Operation",
        required=True,
        default=lambda self: _("New"),
        readonly=True,
        copy=False,
        index="trigram",
        tracking=True,
    )
    amount = fields.Monetary(
        currency_field="currency_id",
        tracking=True,
        help="Operation amount",
    )
    reference = fields.Char(
        copy=False,
        tracking=True,
        help="External reference or description",
    )
    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("in_progress", "In Progress"),
            ("done", "Done"),
            ("cancel", "Cancelled"),
        ],
        required=True,
        default="draft",
        readonly=True,
        copy=False,
        tracking=True,
        help="Workflow execution state",
    )
    date = fields.Date(
        string="Date",
        required=True,
        default=fields.Date.context_today,
        tracking=True,
        help="Reference date for this workflow execution",
    )
    line_ids = fields.One2many(
        comodel_name="automation.runtime.line",
        inverse_name="runtime_id",
        string="Workflow Steps",
        readonly=True,
        help="Per-step execution history",
    )
    progress = fields.Integer(
        string="Progress %",
        compute="_compute_progress",
        compute_sudo=True,
        store=True,
        help="Completion percentage (0-100)",
    )
    progress_display = fields.Char(
        string="Progress",
        compute="_compute_progress_display",
        compute_sudo=True,
        help="Human-readable progress display",
    )

    # =========================================================================
    # CRUD Methods
    # =========================================================================

    @api.model_create_multi
    def create(self, vals_list):
        """Generate sequence name on creation."""
        for vals in vals_list:
            if "company_id" in vals:
                self = self.sudo().with_company(vals["company_id"])

            if vals.get("name", _("New")) == _("New"):
                seq_date = (
                    fields.Datetime.context_timestamp(
                        self,
                        fields.Datetime.to_datetime(vals["date"]),
                    )
                    if "date" in vals
                    else None
                )
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "automation.runtime",
                    sequence_date=seq_date,
                ) or _("New")

        return super().create(vals_list)

    # =========================================================================
    # Computed Fields
    # =========================================================================

    @api.depends("line_ids.state")
    def _compute_progress(self):
        """Calculate workflow completion percentage."""
        for runtime in self:
            total = len(runtime.line_ids)
            if total == 0:
                runtime.progress = 0
                continue
            done = len(runtime.line_ids.filtered(lambda l: l.state == "done"))
            runtime.progress = int(round((done / total) * 100))

    @api.depends("line_ids.state")
    def _compute_progress_display(self):
        """Calculate human-readable progress display."""
        for runtime in self:
            total = len(runtime.line_ids)
            if total == 0:
                runtime.progress_display = "0/0 steps"
                continue
            done = len(runtime.line_ids.filtered(lambda l: l.state == "done"))
            runtime.progress_display = f"{done}/{total} steps"

    # =========================================================================
    # Workflow Actions
    # =========================================================================

    def action_start(self):
        """Start workflow: create per-execution lines from the DAG definition."""
        self.ensure_one()

        if self.state != "draft":
            return

        self._create_action_lines()
        self.state = "in_progress"

        self.message_post(
            body=_("Workflow started with %d steps", len(self.line_ids)),
            subject=_("Workflow Started"),
        )

    def action_run_all(self):
        """Execute all workflow steps, advancing through the DAG until complete.

        Processes all ready branches at each iteration, enabling parallel
        branch execution. Returns when the runtime reaches 'done' or 'cancel'
        or blocks (error / unsatisfied dependency).
        """
        self.ensure_one()

        while self.state == "in_progress":
            ready_lines = self.line_ids.filtered(lambda l: l.state == "ready")
            if not ready_lines:
                break
            for line in ready_lines:
                line.action_execute()

        return self.state

    def action_cancel(self):
        """Cancel workflow and all pending steps."""
        self.ensure_one()

        if self.state in ["done", "cancel"]:
            return

        self.state = "cancel"
        self.line_ids.filtered(
            lambda l: l.state not in ["done", "cancel"],
        ).action_cancel()
        self.message_post(body=_("Workflow cancelled"), subject=_("Workflow Cancelled"))

    def action_done(self):
        """Mark workflow as completed."""
        self.ensure_one()

        if self.state != "in_progress":
            return

        self.state = "done"
        self.message_post(
            body=_("Workflow completed successfully"),
            subject=_("Workflow Completed"),
        )

    def action_next_step(self):
        """Execute the next single ready step (for manual step-by-step mode)."""
        self.ensure_one()

        if self.state != "in_progress":
            raise UserError(_("Workflow is not in progress"))

        ready_lines = self.line_ids.filtered(lambda l: l.state == "ready")

        if not ready_lines:
            incomplete = self.line_ids.filtered(
                lambda l: l.state not in ["done", "cancel"],
            )
            if not incomplete:
                self.action_done()
                return {
                    "type": "ir.actions.client",
                    "tag": "display_notification",
                    "params": {
                        "title": _("Workflow Complete"),
                        "message": _("All workflow steps completed successfully!"),
                        "type": "success",
                    },
                }
            raise UserError(
                _("No actions are ready to execute. Check dependencies."),
            )

        next_line = ready_lines[0]
        context = self._get_execution_context()
        context.update(
            {
                "runtime_id": self.id,
                "runtime_line_id": next_line.id,
            },
        )
        return next_line.with_context(**context).action_execute()

    # =========================================================================
    # Internal Helpers
    # =========================================================================

    def _create_action_lines(self):
        """Create runtime.line records that mirror the automation's DAG definition.

        Faithfully replicates the ``predecessor_ids`` topology from
        ``ir.actions.server`` into isolated ``automation.runtime.line``
        records for this execution. Root actions (no predecessors) start
        as 'ready'; all others start as 'waiting'.
        """
        self.ensure_one()

        actions = self.automation_id.action_server_ids.sorted("sequence")
        if not actions:
            raise UserError(
                _(
                    "Automation '%s' has no server actions configured",
                    self.automation_id.name,
                ),
            )

        # Pass 1: create all lines in 'waiting' state
        line_by_action: dict[int, models.Model] = {}
        for action in actions:
            line = self.env["automation.runtime.line"].create({
                "runtime_id": self.id,
                "action_id": action.id,
                "name": action.name,
                "sequence": action.sequence,
                "state": "waiting",
            })
            line_by_action[action.id] = line

        # Pass 2: wire predecessor relationships using the definition topology
        for action in actions:
            line = line_by_action[action.id]
            predecessor_line_ids = [
                line_by_action[pred.id].id
                for pred in action.predecessor_ids
                if pred.id in line_by_action
            ]
            if predecessor_line_ids:
                line.predecessor_ids = [(6, 0, predecessor_line_ids)]

        # Pass 3: mark root actions (no predecessors in this execution) as ready
        for action in actions:
            if not action.predecessor_ids:
                line_by_action[action.id].state = "ready"

        return self.env["automation.runtime.line"].browse(
            [line.id for line in line_by_action.values()]
        )

    def _get_execution_context(self):
        """Build context dict for action execution."""
        self.ensure_one()
        return {
            "default_partner_id": self.partner_id.id if self.partner_id else False,
            "default_diff_partner_id": (
                self.diff_partner_id.id if self.diff_partner_id else False
            ),
            "default_amount": self.amount,
            "default_currency_id": self.currency_id.id,
            "default_reference": self.reference,
            "default_date": self.date,
            "target_company_id": (
                self.multicompany_id.id if self.multicompany_id else False
            ),
        }

    # =========================================================================
    # Navigation Actions
    # =========================================================================

    def action_view_automation(self):
        """Open the automation workflow definition."""
        self.ensure_one()
        return {
            "name": _("Automation Workflow"),
            "type": "ir.actions.act_window",
            "res_model": "base.automation",
            "view_mode": "form",
            "res_id": self.automation_id.id,
        }

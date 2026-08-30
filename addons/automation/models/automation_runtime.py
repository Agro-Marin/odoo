import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AutomationRuntime(models.Model):
    _name = "automation.runtime"
    _description = "Automation Workflow Runtime Instance"
    _inherit = ["mixin.mail.thread", "mixin.mail.activity"]
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
        comodel_name="automation.rule",
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
            ("error", "Failed"),
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

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            seq_env = self.sudo()
            if "company_id" in vals:
                seq_env = seq_env.with_company(vals["company_id"])

            if vals.get("name", _("New")) == _("New"):
                seq_date = (
                    fields.Datetime.context_timestamp(
                        seq_env,
                        fields.Datetime.to_datetime(vals["date"]),
                    )
                    if "date" in vals
                    else None
                )
                vals["name"] = seq_env.env["ir.sequence"].next_by_code(
                    "automation.runtime",
                    sequence_date=seq_date,
                ) or _("New")

        return super().create(vals_list)

    SETTLED_LINE_STATES = ("done", "cancel", "error")

    def _settled_line_counts(self):
        return {
            runtime.id: (
                len(
                    runtime.line_ids.filtered(
                        lambda l: l.state in self.SETTLED_LINE_STATES,
                    ),
                ),
                len(runtime.line_ids),
            )
            for runtime in self
        }

    @api.depends("line_ids.state")
    def _compute_progress(self):
        counts = self._settled_line_counts()
        for runtime in self:
            settled, total = counts[runtime.id]
            runtime.progress = round((settled / total) * 100) if total else 0

    @api.depends("line_ids.state")
    def _compute_progress_display(self):
        counts = self._settled_line_counts()
        for runtime in self:
            settled, total = counts[runtime.id]
            runtime.progress_display = f"{settled}/{total} steps"

    def action_start(self):
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
        self.ensure_one()

        while self.state == "in_progress":
            ready_lines = self.line_ids.filtered(lambda l: l.state == "ready")
            if not ready_lines:
                blocked = self.line_ids.filtered(
                    lambda l: l.state not in ("done", "cancel", "error"),
                )
                if blocked:
                    _logger.warning(
                        "Runtime %s cannot advance: %s step(s) never became ready (%s).",
                        self.name,
                        len(blocked),
                        ", ".join(blocked.mapped("name")),
                    )
                    blocked.action_mark_error(
                        _("Step never became ready: its dependencies cannot complete."),
                    )
                    self.action_error()
                break
            for line in ready_lines:
                line.action_execute()
                if self.state != "in_progress":
                    break

        stranded = self.line_ids.filtered(
            lambda l: l.state not in ("done", "cancel", "error"),
        )
        if stranded and self.state != "in_progress":
            stranded.action_mark_error(
                _("Step never ran: the workflow already failed."),
            )

        return self.state

    def action_cancel(self):
        self.ensure_one()

        if self.state in ["done", "cancel", "error"]:
            return

        self.state = "cancel"
        self.line_ids.filtered(
            lambda l: l.state not in ["done", "cancel", "error"],
        ).action_cancel()
        self.message_post(body=_("Workflow cancelled"), subject=_("Workflow Cancelled"))

    def action_done(self):
        self.ensure_one()

        if self.state != "in_progress":
            return

        self.state = "done"
        self.message_post(
            body=_("Workflow completed successfully"),
            subject=_("Workflow Completed"),
        )

    def action_error(self):
        self.ensure_one()

        if self.state != "in_progress":
            return

        self.state = "error"
        failed = self.line_ids.filtered(lambda l: l.state == "error")
        self.message_post(
            body=_(
                "Workflow failed at: %(steps)s",
                steps=", ".join(failed.mapped("name")) or _("unknown step"),
            ),
            subject=_("Workflow Failed"),
        )

    def action_next_step(self):
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

    def _create_action_lines(self):
        self.ensure_one()

        actions = self.automation_id.action_server_ids.sorted("sequence")
        if not actions:
            raise UserError(
                _(
                    "Automation '%s' has no server actions configured",
                    self.automation_id.name,
                ),
            )

        lines = self.env["automation.runtime.line"].create(
            [
                {
                    "runtime_id": self.id,
                    "action_id": action.id,
                    "name": action.name,
                    "sequence": action.sequence,
                    "state": "waiting",
                }
                for action in actions
            ]
        )
        line_by_action: dict[int, models.Model] = dict(
            zip(actions.ids, lines, strict=True)
        )

        for action in actions:
            line = line_by_action[action.id]
            predecessor_line_ids = [
                line_by_action[pred.id].id
                for pred in action.predecessor_ids
                if pred.id in line_by_action
            ]
            if predecessor_line_ids:
                line.predecessor_ids = [(6, 0, predecessor_line_ids)]

        for line in line_by_action.values():
            if line._predecessors_satisfied():
                line.state = "ready"

        return self.env["automation.runtime.line"].browse(
            [line.id for line in line_by_action.values()]
        )

    def _get_execution_context(self):
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

    def action_view_automation(self):
        self.ensure_one()
        return {
            "name": _("Automation Workflow"),
            "type": "ir.actions.act_window",
            "res_model": "automation.rule",
            "view_mode": "form",
            "res_id": self.automation_id.id,
        }

import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AutomationRuntimeLine(models.Model):
    _name = "automation.runtime.line"
    _description = "Automation Runtime Action Line"
    _order = "sequence, id"

    runtime_id = fields.Many2one(
        comodel_name="automation.runtime",
        string="Workflow Runtime",
        required=True,
        ondelete="cascade",
        index=True,
    )
    action_id = fields.Many2one(
        comodel_name="ir.actions.server",
        string="Server Action",
        required=True,
        ondelete="restrict",
        help="The server action to execute",
    )
    name = fields.Char(
        string="Step Name",
        required=True,
        help="Description of this workflow step",
    )
    sequence = fields.Integer(
        default=10,
        help="Execution order (lower = earlier)",
    )
    state = fields.Selection(
        selection=[
            ("waiting", "Waiting"),
            ("ready", "Ready"),
            ("in_progress", "In Progress"),
            ("done", "Done"),
            ("cancel", "Cancelled"),
            ("error", "Error"),
        ],
        default="waiting",
        required=True,
        readonly=True,
        copy=False,
        help="Action execution state",
    )
    error_message = fields.Text(
        string="Error Details",
        readonly=True,
        help="Error message if execution failed",
    )

    predecessor_ids = fields.Many2many(
        comodel_name="automation.runtime.line",
        relation="automation_runtime_line_dag",
        column1="successor_id",
        column2="predecessor_id",
        string="Wait For",
        help="This action waits for these predecessors to complete",
    )

    successor_ids = fields.Many2many(
        comodel_name="automation.runtime.line",
        relation="automation_runtime_line_dag",
        column1="predecessor_id",
        column2="successor_id",
        string="Enables",
        readonly=True,
        help="Completing this action enables these successors",
    )

    created_record_ref = fields.Reference(
        string="Created Record",
        selection="_selection_created_record_models",
        readonly=True,
        help="Record created or modified by this action",
    )

    @api.model
    def _selection_created_record_models(self):
        return [
            ("automation.runtime", "Workflow Runtime"),
        ]

    def _predecessors_satisfied(self):
        self.ensure_one()
        return all(pred.state == "done" for pred in self.predecessor_ids)

    def action_mark_ready(self):
        self.write({"state": "ready", "error_message": False})

    def action_cancel(self):
        for line in self:
            if line.state in ["done", "cancel"]:
                continue

            line.state = "cancel"

            if (
                line.created_record_ref
                and line.created_record_ref._name == "automation.runtime"
            ):
                line.created_record_ref.action_cancel()

    def action_mark_done(self):
        self.write({"state": "done", "error_message": False})

        for successor in self.successor_ids:
            if successor.state == "waiting" and successor._predecessors_satisfied():
                successor.action_mark_ready()
                _logger.info(
                    "Action '%s' (#%d) is now ready",
                    successor.name,
                    successor.id,
                )

        incomplete = self.runtime_id.line_ids.filtered(
            lambda l: l.state not in ["done", "cancel"],
        )

        if not incomplete:
            self.runtime_id.action_done()

    def action_mark_error(self, error_msg):
        self.write({"state": "error", "error_message": error_msg})

    def action_execute(self):
        self.ensure_one()

        if self.state not in ("ready", "in_progress"):
            raise UserError(_("Action is not ready to execute"))

        self.write({"state": "in_progress"})

        try:
            ctx = dict(self.env.context)
            runtime = self.runtime_id
            if runtime.res_model and runtime.res_id:
                ctx.update(
                    {
                        "active_model": runtime.res_model,
                        "active_id": runtime.res_id,
                        "active_ids": [runtime.res_id],
                        "runtime_line_id": self.id,
                        "runtime_id": runtime.id,
                    }
                )
            else:
                ctx.update(
                    {
                        "active_model": "automation.runtime",
                        "active_id": runtime.id,
                        "active_ids": [runtime.id],
                        "runtime_line_id": self.id,
                        "runtime_id": runtime.id,
                    }
                )

            _logger.info(
                "Executing action '%s' (#%d) for runtime %s",
                self.name,
                self.action_id.id,
                self.runtime_id.name,
            )

            with self.env.cr.savepoint():
                result = self.action_id.with_context(**ctx).run()

            self.action_mark_done()

            _logger.info("✓ Action '%s' completed successfully", self.name)

            return result or True

        except Exception as e:
            error_msg = str(e)
            _logger.exception(
                "✗ Action '%s' failed: %s",
                self.name,
                error_msg,
            )

            self.action_mark_error(error_msg)
            self.runtime_id.action_error()
            return False

    def action_view_document(self):
        self.ensure_one()

        if not self.created_record_ref:
            raise UserError(_("No document created by this action"))

        return {
            "name": _("Created Record"),
            "type": "ir.actions.act_window",
            "res_model": self.created_record_ref._name,
            "view_mode": "form",
            "res_id": self.created_record_ref.id,
        }

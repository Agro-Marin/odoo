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
            ("paused", "Paused"),
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
    activity_ids = fields.One2many(
        comodel_name="mail.activity",
        inverse_name="automation_runtime_line_id",
        string="Approval Activities",
        readonly=True,
    )
    date_resume = fields.Datetime(
        string="Resumes At",
        readonly=True,
        copy=False,
        help="When a paused Wait step becomes ready again",
    )
    error_message = fields.Text(
        string="Error Details",
        readonly=True,
        help="Error message if execution failed",
    )

    edge_in_ids = fields.One2many(
        comodel_name="automation.runtime.edge",
        inverse_name="target_line_id",
        string="Waits For",
        help="Edges that must be satisfied before this step can execute",
    )

    edge_out_ids = fields.One2many(
        comodel_name="automation.runtime.edge",
        inverse_name="source_line_id",
        string="Enables",
        readonly=True,
        help="Edges this step's outcome can satisfy",
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
        return all(edge._is_satisfied() for edge in self.edge_in_ids)

    def _get_predecessors(self):
        return self.edge_in_ids.source_line_id

    def _get_successors(self):
        return self.edge_out_ids.target_line_id

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

    def _activate_successors(self):
        self.ensure_one()
        for successor in self._get_successors():
            if successor.state == "waiting" and successor._predecessors_satisfied():
                successor.action_mark_ready()
                _logger.info(
                    "Action '%s' (#%d) is now ready",
                    successor.name,
                    successor.id,
                )

    def _has_error_handler(self):
        self.ensure_one()
        return any(
            edge.condition in ("on_error", "always") for edge in self.edge_out_ids
        )

    def action_pause(self):
        resume_at = self.env.cr.now() + self.action_id._get_wait_delta()
        self.write(
            {"state": "paused", "date_resume": resume_at, "error_message": False}
        )
        _logger.info(
            "Step '%s' (#%d) paused until %s",
            self.name,
            self.id,
            resume_at,
        )
        return True

    def action_request_approval(self):
        self.ensure_one()
        record = self.runtime_id._get_target_record()
        if not record:
            self.action_mark_error(
                _("Approval cannot be requested: this run has no target record."),
            )
            self.runtime_id.action_error()
            return False

        activity_type = self.env.ref("mail.mail_activity_data_todo", False)
        summary = self.action_id.approval_note or self.name
        self.env["mail.activity"].create(
            [
                {
                    "res_model_id": self.env["ir.model"]._get_id(record._name),
                    "res_id": record.id,
                    "activity_type_id": activity_type.id if activity_type else False,
                    "summary": summary,
                    "user_id": approver.id,
                    "automation_runtime_line_id": self.id,
                }
                for approver in self.action_id.approval_user_ids
            ]
        )
        self.write({"state": "paused", "date_resume": False, "error_message": False})
        return True

    def action_start_subflow(self):
        self.ensure_one()
        parent = self.runtime_id
        child = self.env["automation.runtime"].create(
            {
                "automation_id": self.action_id.subflow_automation_id.id,
                "res_model": parent.res_model,
                "res_id": parent.res_id,
                "parent_line_id": self.id,
            }
        )
        self.write(
            {
                "state": "paused",
                "date_resume": False,
                "error_message": False,
                "created_record_ref": f"automation.runtime,{child.id}",
            }
        )
        child.action_start()
        child.action_run_all()
        return True

    def action_refuse_approval(self, reason=False):
        for line in self.filtered(lambda step: step.state == "paused"):
            activities = line.activity_ids.filtered("active")
            runtime = line.runtime_id
            if runtime.state == "waiting_resume":
                runtime.state = "in_progress"
            line.action_mark_error(reason or _("Approval was refused."))
            activities.unlink()
            if line._has_error_handler():
                runtime.action_run_all()
            else:
                runtime.action_error()

    def _fail_missing_approval(self):
        for line in self.filtered(
            lambda step: (
                step.state == "paused"
                and step.action_id.node_type == "approval"
                and not step.activity_ids.filtered("active")
            ),
        ):
            runtime = line.runtime_id
            if runtime.state == "waiting_resume":
                runtime.state = "in_progress"
            line.action_mark_error(
                _("The approval activity was removed before anyone acted on it."),
            )
            if line._has_error_handler():
                runtime.action_run_all()
            else:
                runtime.action_error()

    def _check_approval_complete(self):
        approvals = self.filtered(
            lambda step: (
                step.state == "paused" and step.action_id.node_type == "approval"
            ),
        )
        for line in approvals:
            if line.activity_ids.filtered("active"):
                continue
            runtime = line.runtime_id
            if runtime.state == "waiting_resume":
                runtime.state = "in_progress"
            line.action_resume()
            runtime.action_run_all()

    def action_resume(self):
        for line in self.filtered(lambda step: step.state == "paused"):
            line.write({"state": "done", "date_resume": False})
            line._activate_successors()

    def action_mark_done(self):
        self.write({"state": "done", "error_message": False})
        self._activate_successors()

        incomplete = self.runtime_id.line_ids.filtered(
            lambda l: l.state not in ["done", "cancel", "error"],
        )

        if not incomplete:
            self.runtime_id.action_done()

    def action_mark_error(self, error_msg):
        self.write({"state": "error", "error_message": error_msg})
        for line in self:
            line._activate_successors()

    def action_execute(self):
        self.ensure_one()

        if self.state not in ("ready", "in_progress"):
            raise UserError(_("Action is not ready to execute"))

        if self.action_id.node_type == "wait":
            return self.action_pause()

        if self.action_id.node_type == "approval":
            return self.action_request_approval()

        if self.action_id.node_type == "subflow":
            return self.action_start_subflow()

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
            if not self._has_error_handler():
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

import logging

from odoo import fields, models
from odoo.tools.safe_eval import safe_eval

from .workflow_edge import CONDITION_SELECTION, SETTLED_STATES

_logger = logging.getLogger(__name__)


class AutomationRuntimeEdge(models.Model):
    _name = "automation.runtime.edge"
    _description = "Automation Runtime Edge"
    _order = "runtime_id, id"

    runtime_id = fields.Many2one(
        comodel_name="automation.runtime",
        required=True,
        ondelete="cascade",
        index=True,
    )
    source_line_id = fields.Many2one(
        comodel_name="automation.runtime.line",
        string="Source Step",
        required=True,
        ondelete="cascade",
        index=True,
    )
    target_line_id = fields.Many2one(
        comodel_name="automation.runtime.line",
        string="Target Step",
        required=True,
        ondelete="cascade",
        index=True,
    )
    condition = fields.Selection(
        selection=CONDITION_SELECTION,
        default="on_success",
        required=True,
        readonly=True,
    )
    condition_expr = fields.Char(readonly=True)

    def _is_satisfied(self):
        self.check_singleton()
        state = self.source_line_id.state
        if state not in SETTLED_STATES:
            return False
        if self.condition == "on_success":
            return state == "done"
        if self.condition == "on_error":
            return state == "error"
        if self.condition == "always":
            return True
        return self._is_expression_truthy()

    def _is_expression_truthy(self):
        self.check_singleton()
        runtime = self.runtime_id
        context = {
            "runtime": runtime,
            "runtime_line": self.source_line_id,
            "record": runtime._get_target_record(),
            "state": self.source_line_id.state,
        }
        try:
            return bool(safe_eval(self.condition_expr or "False", context))
        except Exception:
            _logger.warning(
                "Edge %s -> %s: condition %r could not be evaluated; "
                "the target stays blocked.",
                self.source_line_id.name,
                self.target_line_id.name,
                self.condition_expr,
                exc_info=True,
            )
            return False

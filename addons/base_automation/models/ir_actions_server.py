import logging

from odoo import _, api, exceptions, fields, models
from odoo.fields import Domain
from odoo.tools.json import scriptsafe as json_scriptsafe

from .base_automation import get_webhook_request_payload

_logger = logging.getLogger(__name__)


class IrActionsServer(models.Model):
    _inherit = "ir.actions.server"

    # =========================================================================
    # Base Automation Integration
    # =========================================================================

    usage = fields.Selection(
        selection_add=[("base_automation", "Automation Rule")],
        ondelete={"base_automation": "cascade"},
    )
    base_automation_id = fields.Many2one(
        comodel_name="base.automation",
        string="Automation Rule",
        index="btree_not_null",
        ondelete="cascade",
    )

    # =========================================================================
    # DAG Dependency Fields (topology only — execution state lives on automation.runtime.line)
    # =========================================================================

    predecessor_ids = fields.Many2many(
        comodel_name="ir.actions.server",
        relation="ir_action_server_dependency_rel",
        column1="successor_id",
        column2="predecessor_id",
        string="Predecessors",
        help="Server actions that must complete before this action can execute",
    )
    successor_ids = fields.Many2many(
        comodel_name="ir.actions.server",
        relation="ir_action_server_dependency_rel",
        column1="predecessor_id",
        column2="successor_id",
        string="Successors",
        readonly=True,
        help="Server actions that depend on this action completing (inverse of predecessor_ids)",
    )

    # =========================================================================
    # Constraints
    # =========================================================================

    @api.constrains("predecessor_ids")
    def _check_no_dag_cycle(self):
        """Prevent cycles in the DAG topology using BFS on the predecessor graph.

        A cycle would exist if the current action is reachable from any of its
        own predecessors by following the predecessor chain.
        """
        for action in self:
            reachable: set[int] = set()
            to_visit: list[int] = list(action.predecessor_ids.ids)
            while to_visit:
                node_id = to_visit.pop()
                if node_id == action.id:
                    raise exceptions.ValidationError(
                        _(
                            "Circular dependency detected: action '%(action)s' "
                            "would create a cycle in the workflow DAG.",
                            action=action.name,
                        )
                    )
                if node_id not in reachable:
                    reachable.add(node_id)
                    node = self.browse(node_id)
                    to_visit.extend(node.predecessor_ids.ids)

    # =========================================================================
    # Computed Fields
    # =========================================================================

    @api.depends("usage")
    def _compute_available_model_ids(self):
        """Restrict available models to the parent automation's model."""
        super()._compute_available_model_ids()
        rule_based = self.filtered(lambda action: action.usage == "base_automation")
        for action in rule_based:
            rule_model = action.base_automation_id.model_id
            action.available_model_ids = (
                rule_model.ids if rule_model in action.available_model_ids else []
            )

    # =========================================================================
    # Action Methods
    # =========================================================================

    def action_open_automation(self):
        """Open the parent automation rule."""
        return {
            "type": "ir.actions.act_window",
            "target": "current",
            "views": [[False, "form"]],
            "res_model": self.base_automation_id._name,
            "res_id": self.base_automation_id.id,
        }

    # =========================================================================
    # Existing Methods (standard base_automation)
    # =========================================================================

    def _get_children_domain(self):
        """Prevent automation actions from being used as multi-action children."""
        return super()._get_children_domain() & Domain("base_automation_id", "=", False)

    def _get_eval_context(self, action=None):
        """Add webhook payload to eval context for code actions."""
        eval_context = super()._get_eval_context(action)
        if action and action.state == "code":
            eval_context["json"] = json_scriptsafe
            payload = get_webhook_request_payload()
            if payload:
                eval_context["payload"] = payload
        return eval_context

    def _get_warning_messages(self):
        """Validate action model matches automation rule model."""
        self.ensure_one()
        warnings = super()._get_warning_messages()

        if (
            self.base_automation_id
            and self.model_id != self.base_automation_id.model_id
        ):
            warnings.append(
                _(
                    "Model of action %(action_name)s should match the one from automated rule %(rule_name)s.",
                    action_name=self.name,
                    rule_name=self.base_automation_id.name,
                ),
            )

        return warnings

    @api.model
    def _warning_depends(self):
        """Add fields that trigger warning recomputation."""
        return super()._warning_depends() + [
            "model_id",
            "base_automation_id",
        ]

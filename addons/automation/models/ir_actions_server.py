import logging

from odoo import _, api, exceptions, fields, models
from odoo.fields import Domain
from odoo.tools.json import scriptsafe as json_scriptsafe

from .automation_rule import get_webhook_request_payload

_logger = logging.getLogger(__name__)


class IrActionsServer(models.Model):
    _inherit = "ir.actions.server"

    usage = fields.Selection(
        selection_add=[("automation", "Automation Rule")],
        ondelete={"automation": "cascade"},
    )
    automation_rule_id = fields.Many2one(
        comodel_name="automation.rule",
        string="Automation Rule",
        index="btree_not_null",
        ondelete="cascade",
    )

    predecessor_ids = fields.Many2many(
        comodel_name="ir.actions.server",
        relation="ir_action_server_dependency_rel",
        column1="successor_id",
        column2="predecessor_id",
        string="Predecessors",
        copy=False,
        help="Server actions that must complete before this action can execute",
    )
    successor_ids = fields.Many2many(
        comodel_name="ir.actions.server",
        relation="ir_action_server_dependency_rel",
        column1="predecessor_id",
        column2="successor_id",
        string="Successors",
        readonly=True,
        copy=False,
        help="Server actions that depend on this action completing (inverse of predecessor_ids)",
    )

    @api.constrains("predecessor_ids", "successor_ids")
    def _check_no_dag_cycle(self):
        for action in self:
            seen: set[int] = set()
            frontier = action.predecessor_ids
            while frontier:
                if action.id in frontier.ids:
                    raise exceptions.ValidationError(
                        _(
                            "Circular dependency detected: action '%(action)s' "
                            "would create a cycle in the workflow DAG.",
                            action=action.name,
                        )
                    )
                seen.update(frontier.ids)
                frontier = frontier.predecessor_ids.filtered(
                    lambda a: a.id not in seen,  # noqa: B023 - evaluated eagerly, this iteration
                )

    @api.constrains("predecessor_ids", "automation_rule_id")
    def _check_predecessors_scope(self):
        for action in self:
            if not action.automation_rule_id:
                continue
            foreign = action.predecessor_ids.filtered(
                lambda p: p.automation_rule_id != action.automation_rule_id,  # noqa: B023 - evaluated eagerly, this iteration
            )
            if foreign:
                raise exceptions.ValidationError(
                    _(
                        "Action '%(action)s' depends on actions belonging to a "
                        "different automation rule: %(foreign)s.\n\n"
                        "Dependencies only order the steps of one automation, so "
                        "a step from another rule can never complete within this "
                        "run. Move the action into this automation, or drop the "
                        "dependency.",
                        action=action.name,
                        foreign=", ".join(foreign.mapped("name")),
                    ),
                )

    def _sorted_by_dependency(self):
        ordered_by_sequence = self.sorted("sequence")

        edges = {
            action.id: set(action.predecessor_ids.ids) & set(self.ids)
            for action in ordered_by_sequence
        }
        if not any(edges.values()):
            return ordered_by_sequence

        remaining = list(ordered_by_sequence)
        settled: set[int] = set()
        ordered = self.browse()
        while remaining:
            ready = [a for a in remaining if edges[a.id] <= settled]
            if not ready:
                return ordered + self.browse([a.id for a in remaining])
            ordered += self.browse([a.id for a in ready])
            settled.update(a.id for a in ready)
            ready_ids = {a.id for a in ready}
            remaining = [a for a in remaining if a.id not in ready_ids]
        return ordered

    @api.depends("usage")
    def _compute_available_model_ids(self):
        super()._compute_available_model_ids()
        rule_based = self.filtered(lambda action: action.usage == "automation")
        for action in rule_based:
            rule_model = action.automation_rule_id.model_id
            action.available_model_ids = (
                rule_model.ids if rule_model in action.available_model_ids else []
            )

    def action_view_automation(self):
        return {
            "type": "ir.actions.act_window",
            "target": "current",
            "views": [[False, "form"]],
            "res_model": self.automation_rule_id._name,
            "res_id": self.automation_rule_id.id,
        }

    def _get_domain_children(self):
        return super()._get_domain_children() & Domain("automation_rule_id", "=", False)

    def _get_eval_context(self, action):
        eval_context = super()._get_eval_context(action)
        if action.state == "code":
            eval_context["json"] = json_scriptsafe
            payload = self.env.context.get("webhook_payload")
            if payload is None:
                payload = get_webhook_request_payload()
            if payload is not None:
                eval_context["payload"] = payload

            line_id = self.env.context.get("runtime_line_id")
            if line_id:
                line = self.env["automation.runtime.line"].browse(line_id)
                eval_context["runtime_line"] = line
                eval_context["runtime"] = line.runtime_id
            elif runtime_id := self.env.context.get("runtime_id"):
                eval_context["runtime"] = self.env["automation.runtime"].browse(
                    runtime_id,
                )
        return eval_context

    def _get_warning_messages(self):
        self.ensure_one()
        warnings = super()._get_warning_messages()

        if (
            self.automation_rule_id
            and self.model_id != self.automation_rule_id.model_id
        ):
            warnings.append(
                _(
                    "Model of action %(action_name)s should match the one from automated rule %(rule_name)s.",
                    action_name=self.name,
                    rule_name=self.automation_rule_id.name,
                ),
            )

        return warnings

    @api.model
    def _get_fields_warning_depends(self):
        return super()._get_fields_warning_depends() + [
            "model_id",
            "automation_rule_id",
        ]

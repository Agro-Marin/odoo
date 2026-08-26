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

    # copy=False on both sides: they are two views of one many2many table, so a
    # copied action would otherwise keep pointing at the source automation's
    # nodes and add itself to the source's successors. base.automation.copy()
    # duplicates the actions and remaps the edges explicitly instead.
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

    # =========================================================================
    # Constraints
    # =========================================================================

    @api.constrains("predecessor_ids", "successor_ids")
    def _check_no_dag_cycle(self):
        """Reject a dependency when the action is reachable from its own predecessors.

        Walks the ancestry a level at a time, reading ``predecessor_ids`` off a
        whole recordset per level so the ORM prefetches it in one query. The
        previous per-node ``browse()`` cost one query per node (measured: 12
        queries for a 12-node chain).
        """
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
                # one read for the whole level, not one per node
                frontier = frontier.predecessor_ids.filtered(
                    lambda a: a.id not in seen,  # noqa: B023 - evaluated eagerly, this iteration
                )

    @api.constrains("predecessor_ids", "base_automation_id")
    def _check_predecessors_scope(self):
        """Every predecessor must belong to the same automation.

        A foreign predecessor used to be accepted and then silently discarded by
        ``automation.runtime._create_action_lines`` — which still refused to mark
        the node ready, leaving the run wedged in ``in_progress`` with nothing
        executed and no error. Rejecting it here is what makes that state
        unreachable; the runtime's own readiness rule is the second half.
        """
        for action in self:
            if not action.base_automation_id:
                continue
            foreign = action.predecessor_ids.filtered(
                lambda p: p.base_automation_id != action.base_automation_id,  # noqa: B023 - evaluated eagerly, this iteration
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

    # =========================================================================
    # DAG Ordering
    # =========================================================================

    def _sorted_by_dependency(self):
        """Return ``self`` topologically ordered, ``sequence`` breaking ties.

        Used by ``base.automation._process`` so that trigger-driven runs respect
        the declared graph. Actions form a DAG (``_check_no_dag_cycle``); should
        a cycle ever survive, the remaining actions are appended in sequence
        order rather than dropped, so nothing silently stops running.
        """
        ordered_by_sequence = self.sorted("sequence")

        # Fast path, and the overwhelmingly common one: no edges at all, so the
        # sequence order already is the answer. This runs on every trigger event,
        # so it must not pay for a graph walk that has nothing to walk.
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
            # a level = every remaining action whose in-set predecessors are settled
            ready = [a for a in remaining if edges[a.id] <= settled]
            if not ready:  # cycle or unresolvable: keep them, in sequence order
                return ordered + self.browse([a.id for a in remaining])
            ordered += self.browse([a.id for a in ready])
            settled.update(a.id for a in ready)
            ready_ids = {a.id for a in ready}
            remaining = [a for a in remaining if a.id not in ready_ids]
        return ordered

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

    def _get_domain_children(self):
        """Prevent automation actions from being used as multi-action children."""
        return super()._get_domain_children() & Domain("base_automation_id", "=", False)

    def _get_eval_context(self, action):
        """Add the webhook payload to the eval context for code actions.

        The payload is taken from ``env.context['webhook_payload']``, which
        ``base.automation._execute_webhook`` sets on both of its paths, and only
        falls back to the live HTTP request when the context does not carry it.

        Sourcing it from the request alone made ``payload`` an artefact of *how*
        the rule was invoked rather than of the webhook itself: present over
        HTTP, silently missing whenever ``_execute_webhook`` was called directly
        — from a test, a retry, a queue worker or another module — where the
        code action would fail with ``NameError: name 'payload' is not defined``.
        """
        eval_context = super()._get_eval_context(action)
        if action.state == "code":
            eval_context["json"] = json_scriptsafe
            payload = self.env.context.get("webhook_payload")
            if payload is None:
                payload = get_webhook_request_payload()
            if payload is not None:
                eval_context["payload"] = payload

            # Expose the execution instance to steps of a workflow run.
            # automation.runtime carries partner_id / amount / reference /
            # company for exactly this purpose, but a step previously had no
            # supported way to read them — the values existed and were
            # unreachable. Both names are recordsets, so a step can also record
            # its own outcome on its line.
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
    def _get_fields_warning_depends(self):
        """Add fields that trigger warning recomputation."""
        return super()._get_fields_warning_depends() + [
            "model_id",
            "base_automation_id",
        ]

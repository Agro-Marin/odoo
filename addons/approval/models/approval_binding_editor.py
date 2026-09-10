from typing import Any

from odoo import api, models


class ApprovalBinding(models.Model):
    _inherit = "approval.binding"

    @api.model
    def create_step_for_button(self, model: str, method=False, action_id=False) -> int:
        """Add an approval step to a button, binding the button first if it has none.

        The binding takes the shape a Studio approval rule always had: Request mode,
        approved on invoke, and the operation left to the next call.
        """
        binding = self._get_binding_for_button(
            model, method, action_id
        ) or self._create_binding_for_button(model, method, action_id)
        category = binding.category_id
        steps = category.with_context(active_test=False).step_ids
        sequence = min(max(steps.mapped("sequence"), default=0) + 1, 9)
        step = self.env["approval.category.step"].create(
            {
                "category_id": category.id,
                "name": self.env._("Step %(sequence)s", sequence=sequence),
                "sequence": sequence,
                "group_id": self.env.ref("base.group_user").id,
                "subject_model_id": binding.model_id.id,
            }
        )
        if not category.notify_sequentially:
            category.notify_sequentially = True
        return step.id

    @api.model
    def action_open_button_steps(
        self, model: str, method=False, action_id=False
    ) -> dict[str, Any]:
        binding = self._get_binding_for_button(
            model, method, action_id
        ) or self._create_binding_for_button(model, method, action_id)
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Approval Steps: %(binding)s", binding=binding.name),
            "res_model": "approval.category.step",
            "view_mode": "list,form",
            "domain": [("category_id", "=", binding.category_id.id)],
            "context": {
                "default_category_id": binding.category_id.id,
                "default_subject_model_id": binding.model_id.id,
                "default_group_id": self.env.ref("base.group_user").id,
            },
        }

    @api.model
    def _get_binding_for_button(self, model: str, method, action_id):
        action = False if method else self._parse_button_action(action_id)
        return self.search(
            [
                ("model_name", "=", model),
                ("method", "=", method or False),
                ("action_id", "=", action),
                ("subject_domain", "=", False),
                ("mode", "!=", "advise"),
            ],
            limit=1,
        )

    @api.model
    def _create_binding_for_button(self, model: str, method, action_id):
        ir_model = self.env["ir.model"]._get(model)
        action = False if method else self._parse_button_action(action_id)
        operation = method or self.env["ir.actions.actions"].browse(action).name
        category = self.env["approval.category"].create(
            {
                "name": self.env._(
                    "%(model)s: %(operation)s", model=ir_model.name, operation=operation
                ),
            }
        )
        return self.create(
            {
                "model_id": ir_model.id,
                "method": method or False,
                "action_id": action,
                "mode": "request",
                "approve_on_invoke": True,
                "run_on_approval": False,
                "category_id": category.id,
            }
        )

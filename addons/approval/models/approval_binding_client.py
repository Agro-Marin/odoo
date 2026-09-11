from typing import Any

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import ormcache


class ApprovalBinding(models.Model):
    _inherit = "approval.binding"

    @api.model
    @ormcache()
    def _get_names_of_gated_models(self) -> frozenset[str]:
        return frozenset(
            self.sudo()
            .with_context(active_test=True)
            .search([("mode", "!=", "advise")])
            .mapped("model_name")
        )

    @api.model
    def get_button_approvals(self, specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            self._get_button_approval(
                spec["model"],
                spec.get("res_id"),
                spec.get("method"),
                spec.get("action_id"),
            )
            for spec in specs
        ]

    @api.model
    def check_button_approval(
        self, model: str, res_id: int, method=False, action_id=False
    ) -> dict[str, Any]:
        records = self._get_records_for_button(model, res_id, "write")
        bindings = self._get_button_bindings(model, method, action_id)
        if not records or not bindings:
            return {"approved": True, "request_id": False}
        result = self._gate(
            records,
            bindings,
            method or bindings[:1].action_id.name,
            lambda runnable: True,
        )
        if result is True:
            return {"approved": True, "request_id": False}
        return {
            "approved": False,
            "request_id": result.get("res_id", False)
            if isinstance(result, dict)
            else False,
        }

    @api.model
    def action_decide_approval(
        self,
        model: str,
        res_id: int,
        method=False,
        action_id=False,
        approve=True,
        step_id=False,
    ) -> dict[str, Any]:
        records = self._get_records_for_button(model, res_id, "write")
        binding = self._get_button_binding_for(records, method, action_id)
        steps = binding._get_button_decision_steps(step_id)
        request = binding._get_button_request(records)
        if request.state == "approved" and records.id in binding._get_covered_ids(
            records
        ):
            raise UserError(
                self.env._(
                    "%(record)s is already approved for this.",
                    record=records.display_name,
                ),
            )
        if request.state != "pending":
            request = binding._raise_requests_for(records)
        request = request.with_user(self.env.user)
        if approve:
            request.action_approve(steps=steps)
        else:
            request.with_context(skip_wizard=True).action_refuse(steps=steps)
        return self._get_button_approval(model, res_id, method, action_id)

    @api.model
    def action_withdraw_decision(
        self,
        model: str,
        res_id: int,
        method=False,
        action_id=False,
        approver_id=False,
        step_id=False,
    ) -> dict[str, Any]:
        records = self._get_records_for_button(model, res_id, "write")
        binding = self._get_button_binding_for(records, method, action_id)
        request = binding._get_button_request(records)
        if not request:
            raise UserError(
                self.env._(
                    "Nothing has been decided on %(record)s yet.",
                    record=records.display_name,
                ),
            )
        request = request.with_user(self.env.user)
        if request.state == "refused":
            request.action_reset_to_draft()
        else:
            request.action_withdraw_approver(approver_id, step_id)
        return self._get_button_approval(model, res_id, method, action_id)

    @api.model
    def _get_button_approval(
        self, model: str, res_id=False, method=False, action_id=False
    ) -> dict[str, Any]:
        records = self._get_records_for_button(model, res_id)
        bindings = self._get_button_bindings(model, method, action_id).filtered(
            lambda binding: binding.mode != "advise"
        )
        if records:
            bindings = bindings.filtered(lambda binding: binding._get_selected(records))
        if not bindings:
            return {"gated": False, "approved": True, "request": False, "steps": []}
        waiting = bindings.filtered(
            lambda binding: (
                not records or records.id not in binding._get_covered_ids(records)
            )
        )
        binding = (waiting or bindings)[:1]
        request = binding._get_button_request(records)
        user = self.env.user
        return {
            "gated": True,
            "approved": bool(records) and not waiting,
            "request": request
            and {
                "id": request.id,
                "state": request.state,
                "can_reopen": request._is_standing_refusal()
                and request._can_reopen_refusal(user),
            },
            "steps": binding._get_button_steps(request, records),
        }

    @api.model
    def _get_records_for_button(self, model: str, res_id, operation: str = "read"):
        records = self.env[model]
        records.check_access(operation)
        if res_id:
            records = records.browse(int(res_id)).exists()
            records.check_access(operation)
        return records

    @api.model
    def _get_button_bindings(self, model: str, method, action_id):
        if method:
            bindings = self._bindings_for(model, method)
        else:
            action = self._parse_button_action(action_id)
            bindings = self._bindings_for_action(action) if action else self.browse()
        return bindings.filtered(lambda binding: binding.model_name == model)

    @api.model
    def _parse_button_action(self, action) -> int | bool:
        if not action:
            return False
        if isinstance(action, int) or str(action).isdigit():
            return int(action)
        record = self.env.ref(str(action), raise_if_not_found=False)
        return record.id if record else False

    @api.model
    def _get_button_binding_for(self, records, method, action_id):
        bindings = self._get_button_bindings(records._name, method, action_id).filtered(
            lambda binding: binding.mode != "advise" and binding._get_selected(records)
        )
        if not records or not bindings:
            raise UserError(
                self.env._(
                    "No approval is asked for this on %(record)s.",
                    record=records.display_name,
                ),
            )
        waiting = bindings.filtered(
            lambda binding: records.id not in binding._get_covered_ids(records)
        )
        return (waiting or bindings)[:1]

    def _get_button_decision_steps(self, step_id):
        self.check_singleton()
        if not step_id:
            return None
        steps = self.category_id.sudo().step_ids.filtered(
            lambda step: step.id == int(step_id)
        )
        if not steps:
            raise UserError(self.env._("That step does not gate this button."))
        return steps.sudo(False)

    def _get_button_request(self, record):
        self.check_singleton()
        Request = self.env["approval.request"].sudo()
        if not record:
            return Request
        if "approval_request_id" in record._fields:
            return record.sudo().approval_request_id
        return Request.search(
            [
                ("binding_id", "=", self.id),
                ("res_model", "=", record._name),
                ("res_id", "=", record.id),
            ],
            order="id desc",
            limit=1,
        )

    def _get_button_steps(self, request, record) -> list[dict[str, Any]]:
        self.check_singleton()
        user = self.env.user
        rows = request.approver_ids
        is_open = not request or request.state in ("new", "pending")
        decided = rows.filtered(
            lambda a: a.state in ("approved", "refused") and a.decided_by_user_id
        )
        steps = rows.step_ids or self.category_id.sudo().step_ids.filtered(
            lambda step: (
                step.active and (not record or step._is_applicable_to_document(record))
            )
        )
        if not steps:
            return [self._get_button_flat_step(request, rows, decided, user, is_open)]
        assignment = request._get_step_assignment() if request else {}
        return [
            {
                "id": step.id,
                "name": step.name,
                "sequence": step.sequence,
                "minimum": step.minimum,
                "exclusive": step.exclusive,
                "can_decide": is_open
                and user.id in step._get_pool_user_ids(record)
                and (not request or request._can_decide_step(step, user)),
                "decisions": [
                    self._get_button_decision(row, request, user, step)
                    for row in assignment.get(step.id, rows.browse())
                    | decided.filtered(
                        lambda a, step=step: (
                            a.state == "refused" and step in a.decided_step_ids
                        )
                    )
                ],
            }
            for step in steps.sorted(lambda step: (step.sequence, step.id))
        ]

    def _get_button_flat_step(self, request, rows, decided, user, is_open):
        self.check_singleton()
        category = self.category_id.sudo()
        if request:
            asked = any(
                row._get_effective_approver() == user and row not in decided
                for row in rows
            )
        else:
            asked = user in category.approver_ids.user_id
        return {
            "id": False,
            "name": category.name,
            "sequence": 0,
            "minimum": request.approval_minimum
            if request
            else category.approval_minimum,
            "exclusive": False,
            "can_decide": is_open and asked,
            "decisions": [
                self._get_button_decision(row, request, user) for row in decided
            ],
        }

    @api.model
    def _get_button_decision(self, row, request, user, step=None) -> dict[str, Any]:
        actor = row.decided_by_user_id
        return {
            "approver_id": row.id,
            "user_id": actor.id,
            "user_name": actor.name,
            "state": row.state,
            "date": fields.Datetime.to_string(row.decision_date)
            if row.decision_date
            else False,
            "can_withdraw": row.state == "approved"
            and request.state in ("pending", "approved")
            and request._can_withdraw_approver(row, user, step),
        }

from typing import Any

from odoo import api, fields, models
from odoo.tools import ormcache


class IrAccessSodFunction(models.Model):
    _inherit = "ir.access.sod.function"

    approval_category_ids = fields.Many2many(
        comodel_name="approval.category",
        string="Approves In",
        help="Being in the pool of an active step of these categories is holding "
        "the duty.",
    )
    approval_types = fields.Char(
        string="Approves Types",
        help="Being in the pool of an active step of a category of these types "
        "(comma-separated, e.g. accounting,payment) is holding the duty.",
    )
    approves_anything = fields.Boolean(
        string="Approves In Any Category",
        help="Being in the pool of any active step is holding the duty.",
    )

    @ormcache("self.id", cache="groups")
    def _get_duty_spec(self) -> dict[str, Any]:
        spec = super()._get_duty_spec()
        if not (
            self.approval_category_ids or self.approval_types or self.approves_anything
        ):
            return spec
        steps = self._get_approval_steps()
        return {
            **spec,
            "approver_user_ids": frozenset(steps.member_ids.user_id._ids),
            "approver_group_ids": frozenset(steps.group_id._ids),
        }

    def _get_approval_steps(self):
        self.check_singleton()
        domain = [("category_id.active", "=", True)]
        if not self.approves_anything:
            types = [kind.strip() for kind in (self.approval_types or "").split(",")]
            domain += [
                "|",
                ("category_id", "in", self.approval_category_ids.ids),
                ("category_id.approval_type", "in", [kind for kind in types if kind]),
            ]
        return self.env["approval.category.step"].search(domain)

    @api.model
    def _holds(self, spec: dict[str, Any], user_id: int, held: frozenset) -> bool:
        if super()._holds(spec, user_id, held):
            return True
        if spec["excluded"] & held:
            return False
        return user_id in spec.get("approver_user_ids", ()) or bool(
            spec.get("approver_group_ids", frozenset()) & held
        )


class ApprovalCategory(models.Model):
    _inherit = "approval.category"

    def write(self, vals):
        result = super().write(vals)
        if {"active", "approval_type"} & vals.keys():
            self.env.registry.clear_cache("groups")
        return result


class ApprovalCategoryStep(models.Model):
    _inherit = "approval.category.step"

    @api.model_create_multi
    def create(self, vals_list):
        steps = super().create(vals_list)
        self.env.registry.clear_cache("groups")
        self.env["ir.access.sod.rule"]._check_users(
            steps.group_id.all_user_ids, "approval_step"
        )
        return steps

    def write(self, vals):
        result = super().write(vals)
        if {"group_id", "active", "category_id"} & vals.keys():
            self.env.registry.clear_cache("groups")
            self.env["ir.access.sod.rule"]._check_users(
                self.group_id.all_user_ids, "approval_step"
            )
        return result

    def unlink(self):
        result = super().unlink()
        self.env.registry.clear_cache("groups")
        return result


class ApprovalCategoryStepMember(models.Model):
    _inherit = "approval.category.step.member"

    @api.model_create_multi
    def create(self, vals_list):
        members = super().create(vals_list)
        self.env.registry.clear_cache("groups")
        self.env["ir.access.sod.rule"]._check_users(members.user_id, "approval_step")
        return members

    def write(self, vals):
        result = super().write(vals)
        if "user_id" in vals:
            self.env.registry.clear_cache("groups")
            self.env["ir.access.sod.rule"]._check_users(self.user_id, "approval_step")
        return result

    def unlink(self):
        result = super().unlink()
        self.env.registry.clear_cache("groups")
        return result

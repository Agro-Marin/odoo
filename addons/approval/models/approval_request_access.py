from odoo import api, models
from odoo.exceptions import AccessError, ValidationError
from odoo.fields import Command

from .approval_utils import is_approval_manager


class ApprovalRequestAccess(models.Model):
    _inherit = "approval.request"

    @api.constrains("date_start", "date_end")
    def _check_date_consistency(self) -> None:
        for request in self:
            if (
                request.date_start
                and request.date_end
                and request.date_start > request.date_end
            ):
                raise ValidationError(
                    self.env._("End date must be after start date."),
                )

    @api.constrains("category_id", "request_owner_id")
    def _check_category_access(self) -> None:
        for request in self:
            category = request.category_id
            owner = request.request_owner_id

            if not category.allowed_user_ids and not category.allowed_group_ids:
                continue

            if owner in category.allowed_user_ids:
                continue

            if owner in category.allowed_group_ids.all_user_ids:
                continue

            raise ValidationError(
                self.env._(
                    "You are not allowed to create requests for category '%(category)s'.\n\n"
                    "This category is restricted to specific users or groups. "
                    "Please contact your administrator if you need access.",
                    category=category.name,
                ),
            )

    def _raise_category_change_blocked(self, previous_category) -> None:
        raise ValidationError(
            self.env._(
                "Cannot change approval category after the request has been confirmed.\n\n"
                "Request: %(name)s\n"
                "Current category: %(category)s\n"
                "Current state: %(state)s\n\n"
                "To change the category, refuse this request and create a new one.",
                name=self.name or self.env._("New"),
                category=previous_category.name,
                state=self.state,
            ),
        )

    def _check_access_unlink(self) -> None:
        if self._skip_check_access():
            return

        for request in self:
            is_owner = request.request_owner_id == self.env.user

            if not is_owner:
                raise AccessError(
                    self.env._(
                        "You can only delete your own approval requests.\n\nRequest: %(name)s\nOwner: %(owner)s",
                        name=request._label(),
                        owner=request.request_owner_id.name,
                    ),
                )

    def _check_access_write(self) -> None:
        if self._skip_check_access():
            return

        current_user = self.env.user
        for request in self:
            if request.request_owner_id == current_user:
                continue
            is_approver = any(
                approver._get_effective_approver() == current_user
                for approver in request.approver_ids
            )
            if is_approver and request.state != "new":
                continue
            if is_approver:
                raise AccessError(
                    self.env._(
                        "You cannot modify this request while it is still a "
                        "draft — only its owner can. You will be able to "
                        "complete your own fields once it is submitted for "
                        "your approval.\n\n"
                        "Request: %(name)s\nOwner: %(owner)s",
                        name=request._label(),
                        owner=request.request_owner_id.name,
                    ),
                )
            raise AccessError(
                self.env._(
                    "You can only modify approval requests where you "
                    "are the owner or an assigned approver.\n\n"
                    "Request: %(name)s\nOwner: %(owner)s",
                    name=request._label(),
                    owner=request.request_owner_id.name,
                ),
            )

    def _check_routing_fields_after_submit(self, vals: dict) -> None:
        if self._skip_check_access():
            return
        touched = set(vals) & (
            self._get_routing_fields_live() - self._get_fields_locked()
        )
        if not touched:
            return
        for request in self:
            if request.state == "new" or request.request_owner_id == self.env.user:
                continue
            raise AccessError(
                self.env._(
                    "Only the request owner or an approval manager can change "
                    "%(fields)s once the request is submitted: it decides who "
                    "approves and how soon the reminders fire.\n\n"
                    "Request: %(name)s",
                    fields=", ".join(sorted(touched)),
                    name=request._label(),
                ),
            )

    def _check_approver_ids_business_rules(self, approver_commands: list) -> None:
        if self.env.su and self.env.context.get("approver_ids_computation"):
            return

        for request in self:
            request_name = request._label()

            for command in approver_commands:
                cmd_type = command[0]

                if cmd_type == Command.UPDATE:
                    continue

                if request.state != "new":
                    raise ValidationError(
                        self.env._(
                            "Cannot modify approver list after request is submitted.\n\n"
                            "Request: %(name)s\n"
                            "Current state: %(state)s\n\n"
                            "The approver list can only be modified while the "
                            "request is a draft. Reset a decided request to "
                            "draft first — the approver list is recomputed "
                            "there.",
                            name=request_name,
                            state=request.state,
                        ),
                    )

    _LOCKED_FIELDS = frozenset(
        {
            "amount",
            "currency_id",
            "quantity",
            "date",
            "date_start",
            "date_end",
            "date_deadline",
            "date_planned",
            "partner_id",
            "reference",
            "location",
            "reason",
            "request_owner_id",
            "company_id",
            "res_model",
            "res_id",
        },
    )

    _SYSTEM_LOCKED_FIELDS = frozenset(
        {
            "approval_minimum",
            "name",
            "date_confirmed",
            "category_snapshot",
        },
    )

    _PENDING_CHANGE_EDITABLE = {
        "date": frozenset({"date", "date_start", "date_end"}),
        "reason": frozenset({"reason"}),
    }

    def _get_fields_locked(self) -> frozenset[str]:
        return self._LOCKED_FIELDS

    def _get_pending_change_candidates(self) -> frozenset[str]:
        self.check_singleton()
        candidates = {"reason"}
        if self.has_date != "no" or self.has_date_range != "no":
            candidates.add("date")
        return frozenset(candidates)

    _COMPUTE_ONLY_FIELDS = frozenset(
        {
            "state",
            "date_approval_granted",
            "date_refused",
            "date_cancelled",
            "approval_deadline",
            "res_model_id",
        },
    )

    def _check_no_forged_computed_fields(self, vals: dict) -> None:
        forged = set(vals) & self._COMPUTE_ONLY_FIELDS
        if forged:
            raise ValidationError(
                self.env._(
                    "%(fields)s cannot be set directly — these are "
                    "computed by the approval workflow itself and change "
                    "only as a consequence of real approver decisions.",
                    fields=", ".join(sorted(forged)),
                ),
            )

    def _check_locked_fields(self, vals: dict) -> None:
        locked = self._get_fields_locked()
        if not self.env.su:
            locked |= self._SYSTEM_LOCKED_FIELDS
        locked_touched = set(vals) & locked
        if not locked_touched:
            return
        may_apply_change = self.env.su or is_approval_manager(self.env)
        for request in self:
            if request.state == "new":
                continue
            editable = (
                self._PENDING_CHANGE_EDITABLE.get(
                    request.pending_change_field, frozenset()
                )
                if may_apply_change or request.request_owner_id == self.env.user
                else frozenset()
            )
            blocked = locked_touched - editable
            if blocked:
                raise ValidationError(
                    self.env._(
                        "Cannot modify %(fields)s after the request has "
                        "been submitted — approvers decide on these "
                        "values.\n\n"
                        "Request: %(name)s\nCurrent state: %(state)s\n\n"
                        "Ask an approver to request a change, or reset "
                        "the request to draft if it was refused or "
                        "cancelled.",
                        fields=", ".join(sorted(blocked)),
                        name=request._label(),
                        state=request.state,
                    ),
                )

    def _check_business_rules_unlink(self) -> None:
        for request in self:
            if request.state != "new":
                raise ValidationError(
                    self.env._(
                        "Cannot delete requests in %(state)s state.\n\n"
                        "Request: %(name)s\n\n"
                        "Once submitted, requests can only be refused or "
                        "cancelled — they remain on file as part of the "
                        "audit trail.",
                        name=request._label(),
                        state=request.state,
                    ),
                )

    def _skip_check_access(self) -> bool:
        return self.env.su or is_approval_manager(self.env)

    def _check_owner_or_manager(self, action_label: str) -> None:
        if self.env.su or is_approval_manager(self.env):
            return
        for request in self:
            if request.request_owner_id != self.env.user:
                raise AccessError(
                    self.env._(
                        "Only the request owner or an approval manager "
                        "can %(action)s this request.\n\n"
                        "Request: %(name)s\nOwner: %(owner)s",
                        action=action_label,
                        name=request.display_name,
                        owner=request.request_owner_id.name,
                    ),
                )

    def _check_decision_actor(self, approver: models.BaseModel) -> None:
        if self.env.su:
            return
        current_user = self.env.user
        impersonated = approver.filtered(
            lambda a: a._get_effective_approver() != current_user,
        )
        if impersonated:
            raise AccessError(
                self.env._(
                    "You are not the assigned approver for this decision.\n\n"
                    "Request: %(name)s",
                    name=self.display_name,
                ),
            )

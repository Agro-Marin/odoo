from odoo import api, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import Command

from .approval_utils import is_approval_manager


class ApprovalRequestValidation(models.Model):
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

    @api.constrains("approver_ids")
    def _check_approver_ids(self) -> None:
        for request in self:
            user_ids = request.approver_ids.mapped("user_id").ids
            if len(user_ids) != len(set(user_ids)):
                raise ValidationError(
                    self.env._(
                        "You cannot assign the same approver multiple times on the same request.",
                    ),
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

    def _check_access_approver_ids(self, approver_commands: list) -> None:
        if self._skip_check_access():
            return

        approval_approver = self.env["approval.approver"]
        current_user = self.env.user

        for request in self:
            request_name = request._label()

            for command in approver_commands:
                cmd_type = command[0]

                if cmd_type == Command.CREATE:
                    raise AccessError(
                        self.env._(
                            "Approvers cannot be added manually.\n\n"
                            "Approvers are defined by the approval category and "
                            "managed automatically.\n\n"
                            "Request: %(name)s",
                            name=request_name,
                        ),
                    )

                if cmd_type == Command.UPDATE:
                    approver_id = command[1]
                    approver = approval_approver.browse(approver_id)
                    effective_approver = approver._get_effective_approver()
                    is_effective_approver = effective_approver == current_user

                    if not is_effective_approver:
                        if approver.is_delegated:
                            raise AccessError(
                                self.env._(
                                    "This approval is currently delegated to %(delegate)s.\n\n"
                                    "Request: %(name)s\nOriginal approver: %(approver)s",
                                    name=request_name,
                                    approver=approver.user_id.name,
                                    delegate=approver.delegate_id.name,
                                ),
                            )
                        raise AccessError(
                            self.env._(
                                "Only the assigned approver can modify their approval record.\n\n"
                                "Request: %(name)s\nApprover: %(approver)s",
                                name=request_name,
                                approver=approver.user_id.name,
                            ),
                        )

                elif cmd_type in (Command.DELETE, Command.UNLINK):
                    approver_id = command[1]
                    approver = approval_approver.browse(approver_id)
                    raise AccessError(
                        self.env._(
                            "Approvers cannot be removed from requests.\n\n"
                            "Approvers are defined by the approval category and "
                            "managed automatically.\n\n"
                            "Request: %(name)s\nApprover: %(approver)s",
                            name=request_name,
                            approver=approver.user_id.name,
                        ),
                    )

                elif cmd_type == Command.LINK:
                    raise AccessError(
                        self.env._(
                            "Approvers cannot be linked manually.\n\n"
                            "Approvers are defined by the approval category and "
                            "managed automatically.\n\n"
                            "Request: %(name)s",
                            name=request_name,
                        ),
                    )

                elif cmd_type in (Command.CLEAR, Command.SET):
                    raise AccessError(
                        self.env._(
                            "Approvers cannot be replaced manually.\n\n"
                            "Approvers are defined by the approval category and "
                            "managed automatically.\n\n"
                            "Request: %(name)s",
                            name=request_name,
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
        self.ensure_one()
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

    def _check_approve_sequentially_can_approve(self, candidate) -> None:
        if self.approve_sequentially and any(a.state == "waiting" for a in candidate):
            raise ValidationError(
                self.env._("You cannot approve before the previous approver.")
            )

    def _check_confirm(self) -> None:
        self._check_enough_approvers()
        self._check_has_document_has_attachment()
        self._check_category_required_fields()

    def _check_enough_approvers(self) -> None:
        self.ensure_one()
        if len(self.approver_ids) < self.approval_minimum:
            raise UserError(
                self.env._(
                    "You have to add at least %(count)d approver(s) to "
                    "confirm your request.",
                    count=self.approval_minimum,
                ),
            )

    def _check_has_document_has_attachment(self) -> None:
        if self.has_document == "required" and not self.count_attachment:
            raise UserError(self.env._("You have to attach at least one document."))

        if self.has_document != "required":
            return
        requirements = self.category_id.document_requirement_ids.filtered("required")
        if not requirements:
            return

        satisfied = self.attachment_ids.approval_requirement_id
        missing = requirements - satisfied
        if missing:
            raise UserError(
                self.env._(
                    "Missing required documents: %(missing)s\n\n"
                    "Attach a file for each, and set its 'Satisfies "
                    "Requirement' so the approvers know which document is "
                    "which.",
                    missing=", ".join(missing.mapped("name")),
                ),
            )

    def _check_category_required_fields(self) -> None:
        field_mapping = self._get_category_required_field_mapping()
        missing_fields = []

        for has_field, (field_name, field_label) in field_mapping.items():
            has_value = getattr(self, has_field, "no")
            if has_value == "required":
                if self._is_required_field_skipped(has_field):
                    continue
                field_value = getattr(self, field_name, None)
                if not field_value:
                    missing_fields.append(field_label)

        if self.has_date_range == "required" and not self.date_end:
            missing_fields.append(self.env._("Period End Date"))

        if missing_fields:
            raise UserError(
                self.env._(
                    "The following required fields are empty:\n\n%(fields)s\n\n"
                    "Please fill them before submitting the request.",
                    fields="\n".join(f"- {f}" for f in missing_fields),
                ),
            )

    def _is_required_field_skipped(self, has_field: str) -> bool:
        return False

    def _get_category_required_field_mapping(
        self,
    ) -> dict[str, tuple[str, str]]:
        return {
            "has_date": ("date", self.env._("Date")),
            "has_date_deadline": ("date_deadline", self.env._("Deadline")),
            "has_date_planned": ("date_planned", self.env._("Planned Date")),
            "has_date_range": ("date_start", self.env._("Period Start Date")),
            "has_partner": ("partner_id", self.env._("Contact")),
            "has_quantity": ("quantity", self.env._("Quantity")),
            "has_amount": ("amount", self.env._("Amount")),
            "has_reference": ("reference", self.env._("Reference")),
            "has_location": ("location", self.env._("Location")),
        }

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

    def _check_withdraw_allowed(self) -> None:
        pass

    def _check_reset_allowed(self) -> None:
        self.ensure_one()
        if not self.res_model or not self.res_id:
            return
        source_doc = self.get_source_document()
        if not source_doc or not source_doc.exists():
            return
        linked_request_id = getattr(source_doc, "approval_request_id", None)
        if linked_request_id is not None and linked_request_id.id != self.id:
            raise UserError(
                self.env._(
                    "This request cannot be reset: the source document "
                    "%(doc)s no longer references it. Request a new "
                    "approval from the document instead.",
                    doc=source_doc.display_name,
                ),
            )

    def _raise_withdraw_blocked(self, active_descendants, doc_label):
        if not active_descendants:
            return
        raise UserError(
            self.env._(
                "You cannot withdraw this approval because it has "
                "%(count)d active %(label)s(s) linked.\n\n"
                "Cancel the related %(label)s(s) first, then withdraw.",
                count=len(active_descendants),
                label=doc_label,
            ),
        )

    def _skip_check_access(self) -> bool:
        return self.env.su or is_approval_manager(self.env)

import logging
from typing import Any

from odoo import fields, models
from odoo.exceptions import AccessError, MissingError, UserError, ValidationError
from odoo.fields import Command
from odoo.libs.text import nl2br

from .approval_utils import is_approval_manager

_logger = logging.getLogger(__name__)


class ApprovalRequestLifecycle(models.Model):
    _inherit = "approval.request"

    def _check_bulk_decision_allowed(self) -> None:
        for request in self:
            if request.state != "pending":
                raise UserError(
                    self.env._(
                        "Request '%(request)s' is not in pending state (current: %(state)s).",
                        request=request.name,
                        state=request.state,
                    ),
                )
            if not request._get_current_pending_approver():
                raise UserError(
                    self.env._(
                        "You don't have pending approval rights for request: %s",
                        request.name,
                    ),
                )

    def _action_bulk_decision(
        self,
        action_method: str,
        action_label: str,
        past_tense: str,
        before: Any = None,
    ) -> dict[str, Any]:
        self._check_bulk_decision_allowed()

        success_count = 0
        failed_requests = []
        for request in self:
            try:
                with self.env.cr.savepoint():
                    if before is not None:
                        before(request)
                    getattr(request.with_context(skip_wizard=True), action_method)()
                success_count += 1
            except (UserError, ValidationError) as e:
                failed_requests.append((request.name, str(e)))
                request.message_post(
                    body=self.env._(
                        "Bulk %(action)s failed: %(error)s",
                        action=action_label,
                        error=str(e),
                    ),
                    message_type="notification",
                )
            except Exception as e:
                _logger.exception(
                    "Unexpected error in bulk %s for request %s",
                    action_label,
                    request.name,
                )
                failed_requests.append(
                    (request.name, self.env._("Unexpected error occurred"))
                )
                request.message_post(
                    body=self.env._(
                        "Bulk %(action)s failed with unexpected error: %(error)s",
                        action=action_label,
                        error=str(e),
                    ),
                    message_type="notification",
                )

        if failed_requests:
            failure_details = "\n".join(
                [f"• {name}: {error}" for name, error in failed_requests],
            )
            message = self.env._(
                "%(success)s of %(total)s request(s) %(action)s successfully.\n\nFailed requests:\n%(failures)s",
                success=success_count,
                total=len(self),
                action=past_tense,
                failures=failure_details,
            )
            notification_type = "warning" if success_count > 0 else "danger"
        else:
            message = self.env._(
                "%(count)s approval request(s) %(action)s successfully",
                count=success_count,
                action=past_tense,
            )
            notification_type = "success"

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": notification_type,
                "message": message,
                "sticky": bool(failed_requests),
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

    def action_approve_bulk(self) -> dict[str, Any]:
        return self._action_bulk_decision("action_approve", "approval", "approved")

    def _raise_not_assigned_approver(self) -> None:
        raise UserError(
            self.env._(
                "You are not assigned as an approver for this request, "
                "or your approval has already been processed.",
            ),
        )

    def _apply_decision(
        self,
        decision: str,
        approver: models.BaseModel | None = None,
    ) -> None:
        self.check_singleton()
        assert decision in ("approve", "refuse")
        approver_state = "approved" if decision == "approve" else "refused"
        self._lock_and_reload(with_approvers=True)
        if self.state != "pending":
            raise UserError(
                self.env._(
                    "This request can no longer be %(decision)s: it is "
                    "in state '%(state)s'.",
                    decision=self.env._("approved")
                    if decision == "approve"
                    else self.env._("refused"),
                    state=self.state,
                ),
            )
        old_state = self.state
        if not isinstance(approver, models.BaseModel):
            candidate = self.approver_ids.filtered(
                lambda a: a._get_effective_approver() == self.env.user,
            )
        else:
            candidate = approver.filtered(lambda a: a.request_id == self)
        if decision == "approve":
            self._check_approve_sequentially_can_approve(candidate)
        approver = candidate.filtered(lambda a: a.state == "pending")
        self._check_decision_actor(approver)
        if not approver:
            self._raise_not_assigned_approver()
        acting_user = approver[:1]._get_effective_approver()
        approver.sudo().write(
            {
                "state": approver_state,
                "decision_date": fields.Datetime.now(),
                "decided_by_user_id": acting_user.id,
            },
        )
        if decision == "approve":
            body = self.env._(
                "The request created on %(create_date)s by %(request_owner)s has been accepted.",
                create_date=self.create_date.date(),
                request_owner=self.request_owner_id.name,
            )
            subject = self.env._(
                "The request %(request_name)s for %(request_owner)s has been accepted",
                request_name=self.display_name,
                request_owner=self.request_owner_id.name,
            )
        else:
            body = self.env._(
                "The request created on %(create_date)s by %(request_owner)s has been refused.",
                create_date=self.create_date.date(),
                request_owner=self.request_owner_id.name,
            )
            subject = self.env._(
                "The request %(request_name)s for %(request_owner)s has been refused",
                request_name=self.display_name,
                request_owner=self.request_owner_id.name,
            )
        self.with_user(acting_user).sudo().message_post(
            body=body,
            subject=subject,
            author_id=acting_user.partner_id.id,
            message_type="notification",
            partner_ids=self.request_owner_id.partner_id.ids,
        )
        if decision == "approve":
            self.sudo()._update_next_approvers_state(
                approver,
                "pending",
                only_next_approver=True,
            )
        else:
            self.sudo()._update_next_approvers_state(
                approver,
                "refused",
                only_next_approver=False,
                cancel_activities=True,
            )
            if not self.approve_sequentially:
                self._flip_unsettled_approvers("refused")
        self._get_user_approval_activities(user=acting_user).sudo().action_feedback()
        if self.state in self._TERMINAL_STATES:
            self._cancel_activities()
        if self.state == "approved":
            self.approver_ids.sudo().filtered(
                lambda a: a.state == "pending",
            ).write({"state": "waiting"})
        self._notify_if_terminal_transition(old_state)
        self._log_cycle("decide", decision=decision, actor=acting_user.login)
        if decision == "refuse" and self.state == "refused":
            self._refuse_approval_request()

    def action_approve(
        self,
        approver: models.BaseModel | None = None,
    ) -> dict[str, Any] | None:
        self.check_singleton()
        self._check_no_pending_change("approve")
        self._apply_decision("approve", approver)

    def _refuse_cascade(self) -> bool:
        self.check_singleton()
        if self.state in self._TERMINAL_STATES or self.state == "new":
            return False
        target_state = self._get_parent_cancel_state()
        if target_state == "refused":
            self._force_terminal(
                "refused",
                body=self.env._(
                    "Refused automatically because the parent document was cancelled.",
                ),
                refusal_reason=self.env.ref("approval.refusal_reason_parent_cancelled"),
                refusal_note=self.env._("Parent document was cancelled."),
            )
        else:
            self._force_terminal(
                target_state,
                body=self.env._(
                    "Cancelled automatically because the parent document "
                    "was cancelled.",
                ),
            )
        return True

    def _get_parent_cancel_state(self) -> str:
        return "refused"

    def _check_no_pending_change(self, action_verb: str) -> None:
        if any(self.mapped("pending_change_field")):
            raise UserError(
                self.env._(
                    "You cannot %(verb)s this request while a change is "
                    "pending. Wait for the requester to update the "
                    "requested field and re-submit.",
                    verb=action_verb,
                ),
            )

    def _check_change_request_allowed(self) -> None:
        self.check_singleton()
        if self.state != "pending":
            raise UserError(
                self.env._(
                    "A change can only be requested while the approval is "
                    "pending. Current state: %(state)s",
                    state=self.state,
                ),
            )
        if self.pending_change_field:
            raise UserError(
                self.env._(
                    "A change is already pending on this request (field "
                    "%(field)s). Wait for the requester to re-submit.",
                    field=self.pending_change_field,
                ),
            )

    def action_request_change(
        self,
        approver: models.BaseModel | None = None,
    ) -> dict[str, Any] | None:
        self.check_singleton()

        self._check_change_request_allowed()

        if approver is None and not self.env.context.get("skip_wizard"):
            return self._get_decision_wizard_action("change")

        if not isinstance(approver, models.BaseModel):
            approver = self._get_current_pending_approver()
        else:
            approver = approver.filtered(
                lambda a: a.request_id == self and a.state == "pending",
            )
        self._check_decision_actor(approver)
        if not approver:
            self._raise_not_assigned_approver()

        self._lock_and_reload()
        self._check_change_request_allowed()

        requested_field = self.env.context.get("requested_change_field")
        if requested_field not in self._PENDING_CHANGE_EDITABLE:
            raise UserError(
                self.env._(
                    "Internal: requested_change_field context value must "
                    "be one of %(allowed)s.",
                    allowed=", ".join(sorted(self._PENDING_CHANGE_EDITABLE)),
                ),
            )
        candidates = self._get_pending_change_candidates()
        if requested_field not in candidates:
            raise UserError(
                self.env._(
                    "The '%(field)s' field is not available on category "
                    "'%(category)s', so the requester would have nothing "
                    "to change.\n\nAsk for a change on: %(allowed)s — or "
                    "refuse the request instead.",
                    field=requested_field,
                    category=self.category_id.name,
                    allowed=", ".join(sorted(candidates)),
                ),
            )
        self.sudo().write({"pending_change_field": requested_field})
        self._schedule_change_request_activity(
            requested_field,
            self.env.context.get("requested_change_note") or "",
        )
        return None

    def _schedule_change_request_activity(self, field_name: str, note: str) -> None:
        self.check_singleton()
        field_label = dict(
            self._fields["pending_change_field"]._description_selection(self.env)
        )[field_name]
        self.activity_schedule(
            "approval.mail_activity_data_change_request",
            user_id=self.request_owner_id.id,
            summary=self.env._("Change requested on %s", field_label),
            note=nl2br(note) if note else False,
        )

    def action_resubmit(self) -> None:
        self.check_singleton()
        if not self.pending_change_field:
            raise UserError(
                self.env._(
                    "There is no pending change on this request.",
                ),
            )
        is_owner = self.request_owner_id == self.env.user
        is_manager = is_approval_manager(self.env)
        if not (is_owner or is_manager or self.user_approver_state):
            raise UserError(
                self.env._(
                    "Only the request owner or an approver can re-submit "
                    "after a requested change.",
                ),
            )
        previous_field = self.pending_change_field
        self.sudo().write({"pending_change_field": False})
        self._get_change_request_activities().sudo().action_feedback()
        added = self._extend_approvers_live()
        undone = self.approver_ids.filtered(lambda a: a.state == "approved")
        if undone:
            undone.sudo().write(
                {
                    "state": "waiting",
                    "decision_date": False,
                    "decided_by_user_id": False,
                },
            )
            self._cancel_activities()
            self._open_approval_round(
                self.approver_ids.filtered(
                    lambda a: a.state in ("pending", "waiting"),
                ),
            )
        self.message_post(
            body=self.env._(
                "Re-submitted after the requested change to %(field)s.",
                field=previous_field,
            )
            if not undone
            else self.env._(
                "Re-submitted after the requested change to %(field)s. "
                "%(count)d earlier approval(s) were reset: they were given "
                "on the previous value.",
                field=previous_field,
                count=len(undone),
            ),
            message_type="notification",
        )
        self._log_cycle(
            "resubmit",
            field=previous_field,
            reset=len(undone),
            added=len(added),
        )

    def action_confirm(self) -> None:
        self._sync_approvers()
        to_open = self.env["approval.approver"]
        confirmed = self.env["approval.request"]
        for request in self:
            request._lock_and_reload()

            if request.state != "new":
                raise UserError(
                    self.env._(
                        "Only requests in draft state can be confirmed. "
                        "Request '%(name)s' is currently in state "
                        "'%(state)s'.",
                        name=request._label(),
                        state=request.state,
                    ),
                )

            old_state = request.state
            request._check_confirm()

            if not request.name:
                request.name = request.category_id.sequence_id.next_by_id()

            request.category_snapshot = request._prepare_category_snapshot()

            request.write({"date_confirmed": fields.Datetime.now()})

            auto_action = request._check_auto_action_rules()
            if auto_action:
                request._notify_if_terminal_transition(old_state)
                continue

            to_open |= request.approver_ids.filtered(lambda a: a.state == "new")
            confirmed |= request

        self._open_approval_round(to_open)

        for request in confirmed:
            request._log_cycle("confirm", sequential=request.approve_sequentially)

    def _open_approval_round(self, approvers: models.BaseModel) -> None:
        rows_by_request: dict[int, list[int]] = {}
        for approver in approvers:
            rows_by_request.setdefault(approver.request_id.id, []).append(approver.id)

        to_wait = self.env["approval.approver"]
        to_open = self.env["approval.approver"]
        for request in self:
            row_ids = rows_by_request.get(request.id)
            if not row_ids:
                continue
            rows = approvers.browse(row_ids)
            if request.approve_sequentially:
                ordered = rows.sorted(lambda a: (a.sequence, a.id))
                to_wait |= ordered[1:]
                rows = ordered[:1]
            to_open |= rows

        if to_wait:
            to_wait.sudo().write({"state": "waiting"})
        to_open._create_activity()
        to_open.sudo().write({"state": "pending"})

    def action_cancel(self) -> None:
        self._check_owner_or_manager(self.env._("cancel"))
        for request in self:
            request._lock_and_reload()
            if request.state != "pending":
                raise UserError(
                    self.env._(
                        "Only submitted requests can be cancelled. "
                        "Request '%(name)s' is in state '%(state)s' — "
                        "draft requests can simply be deleted.",
                        name=request.display_name,
                        state=request.state,
                    ),
                )
            request._force_terminal(
                "cancelled",
                body=self.env._(
                    "Request cancelled by %(user)s.",
                    user=self.env.user.name,
                ),
            )

    def action_reset_to_draft(self) -> None:
        for request in self:
            request._lock_and_reload()
            if request.state not in self._TERMINAL_STATES:
                raise UserError(
                    self.env._(
                        "Only decided requests can be reset to draft. "
                        "Request '%(name)s' is in state '%(state)s'.",
                        name=request.display_name,
                        state=request.state,
                    ),
                )
            if request.state == "approved":
                if not (self.env.su or is_approval_manager(self.env)):
                    raise AccessError(
                        self.env._(
                            "Only an approval manager can reset an approved "
                            "request. Request: %(name)s",
                            name=request.display_name,
                        ),
                    )
                request._check_withdraw_allowed()
            else:
                request._check_owner_or_manager(self.env._("reset to draft"))
            request._check_reset_allowed()
            previous_state = request.state
            request._close_pending_change()
            request.approver_ids.sudo().write(
                {
                    "state": "new",
                    "refusal_reason_id": False,
                    "note": False,
                    "decision_date": False,
                    "decided_by_user_id": False,
                    "pending_since": False,
                },
            )
            request.sudo().write(
                {
                    "refusal_reason_id": False,
                    "refusal_note": False,
                    "date_confirmed": False,
                    "category_snapshot": False,
                    "last_reminder_date": False,
                    "reminder_count": 0,
                    "escalated_to_manager": False,
                    "applied_rule_ids": [Command.clear()],
                },
            )
            request._sync_approvers()
            if previous_state == "approved":
                request._notify_source_document_state_change("new")
            request._log_cycle("reset", was=previous_state)
            request.message_post(
                body=self.env._(
                    "Reset to draft from '%(state)s' by %(user)s.",
                    state=previous_state,
                    user=self.env.user.name,
                ),
                message_type="notification",
            )

    def action_refuse_bulk(self) -> dict[str, Any]:
        self._check_bulk_decision_allowed()
        return {
            "name": self.env._("Refuse Requests"),
            "type": "ir.actions.act_window",
            "res_model": "approval.decision.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_request_ids": [Command.set(self.ids)],
                "default_decision_type": "refuse",
            },
        }

    def action_refuse(
        self, approver: models.BaseModel | None = None
    ) -> dict[str, Any] | None:
        self.check_singleton()
        self._check_no_pending_change("refuse")

        if approver is None and not self.env.context.get("skip_wizard"):
            return self._get_decision_wizard_action("refuse")

        self._apply_decision("refuse", approver)
        return None

    def _get_decision_wizard_action(self, decision_type: str) -> dict[str, Any]:
        self.check_singleton()
        current_approver = self._get_current_pending_approver()[:1]
        if not current_approver:
            self._raise_not_assigned_approver()
        titles = {
            "refuse": self.env._("Refuse Request"),
            "change": self.env._("Request a Change"),
        }
        return {
            "name": titles[decision_type],
            "type": "ir.actions.act_window",
            "res_model": "approval.decision.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_approver_id": current_approver.id,
                "default_decision_type": decision_type,
            },
        }

    def _refuse_approval_request(self) -> None:
        return

    def action_withdraw(
        self, approver: models.BaseModel | None = None
    ) -> dict[str, Any] | None:
        self._lock_and_reload(with_approvers=True)
        current_user = self.env.user
        explicit_approver = approver if isinstance(approver, models.BaseModel) else None
        for request in self:
            if request.state not in ("pending", "approved"):
                raise UserError(
                    self.env._(
                        "You cannot withdraw an approval on a %(state)s "
                        "request. Use Reset to Draft to reopen it.",
                        state=request.state,
                    ),
                )
            if explicit_approver is not None:
                req_approver = explicit_approver.filtered(
                    lambda a, req=request: (
                        a.request_id == req and a.state == "approved"
                    ),
                )
            else:
                req_approver = request.approver_ids.filtered(
                    lambda a, user=current_user: (
                        a._get_effective_approver() == user and a.state == "approved"
                    ),
                )

            if not req_approver:
                raise UserError(
                    self.env._(
                        "You cannot withdraw this approval.\n\n"
                        "You are not assigned as an approver for this request, "
                        "or you have not approved it.",
                    ),
                )

            request._check_withdraw_allowed()

            old_state = request.state

            request.sudo()._update_next_approvers_state(
                req_approver,
                "waiting",
                only_next_approver=False,
                cancel_activities=True,
            )

            req_approver.sudo().write(
                {
                    "state": "pending",
                    "decision_date": False,
                    "decided_by_user_id": False,
                },
            )

            still_approved = request.state == "approved"

            if still_approved:
                req_approver.sudo().write({"state": "waiting"})
            else:
                req_approver._create_activity()

                if old_state == "approved" and not request.approve_sequentially:
                    parked = request.approver_ids.filtered(
                        lambda a: a.state == "waiting",
                    )
                    parked.sudo().write({"state": "pending"})
                    parked._create_activity()

            acting_user = req_approver[:1]._get_effective_approver()
            request.with_user(acting_user).sudo().message_post(
                body=self.env._(
                    "%(user)s withdrew their approval. The request is pending review again.",
                    user=acting_user.name,
                )
                if not still_approved
                else self.env._(
                    "%(user)s withdrew their approval. The request stays "
                    "approved: the remaining approvals still satisfy it.",
                    user=acting_user.name,
                ),
                author_id=acting_user.partner_id.id,
                message_type="notification",
            )

            request._log_cycle(
                "withdraw",
                actor=acting_user.login,
                was=old_state,
                reopened=not still_approved,
            )

            if old_state == "approved" and request.state != "approved":
                request._notify_source_document_state_change("pending")

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
        self.check_singleton()
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

    def _check_withdraw_allowed(self) -> None:
        pass

    def _check_reset_allowed(self) -> None:
        self.check_singleton()
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

    def _cancel_activities(self) -> None:
        approval_activity = self.env.ref("approval.mail_activity_data_approval")
        activities = self.activity_ids.filtered(
            lambda a: a.activity_type_id == approval_activity,
        )
        activities.sudo().unlink()

    def _get_request_activities(self, activity_xmlid: str, user: Any = None) -> Any:
        domain = [
            ("res_model", "=", "approval.request"),
            ("res_id", "in", self.ids),
            ("activity_type_id", "=", self.env.ref(activity_xmlid).id),
        ]
        if user:
            domain.append(("user_id", "=", user.id))
        return self.env["mail.activity"].search(domain)

    def _get_user_approval_activities(self, user: Any) -> Any:
        return self._get_request_activities(
            "approval.mail_activity_data_approval", user=user
        )

    def _get_change_request_activities(self) -> Any:
        return self._get_request_activities(
            "approval.mail_activity_data_change_request"
        )

    def _lock_for_approval_action(self) -> None:
        if not self.ids:
            return

        self.env.cr.execute(
            """
            SELECT id FROM approval_request
            WHERE id = ANY(%s)
            ORDER BY id
            FOR UPDATE
            """,
            [list(self.ids)],
        )

    def _lock_and_reload(self, with_approvers: bool = False) -> None:
        self._lock_for_approval_action()
        if with_approvers:
            self.approver_ids.invalidate_recordset(["state"])
        self.invalidate_recordset(["state"])

    def _flip_unsettled_approvers(self, new_state: str) -> None:
        self.check_singleton()
        settled = self.approver_ids._SETTLED_STATES
        self.approver_ids.sudo().filtered(
            lambda a: a.state not in settled,
        ).write({"state": new_state})

    def _stamp_refusal_metadata(
        self,
        refusal_reason: models.BaseModel | None,
        refusal_note: str | None,
    ) -> None:
        self.check_singleton()
        vals: dict[str, Any] = {}
        if refusal_reason and not self.refusal_reason_id:
            vals["refusal_reason_id"] = refusal_reason.id
        if refusal_note and not self.refusal_note:
            vals["refusal_note"] = refusal_note
        if vals:
            self.sudo().write(vals)

    def _force_terminal(
        self,
        new_state: str,
        body: str,
        refusal_reason: models.BaseModel | None = None,
        refusal_note: str | None = None,
        subtype_xmlid: str | None = None,
    ) -> None:
        if new_state not in self._TERMINAL_STATES - {"approved"}:
            raise ValueError(
                f"_force_terminal() accepts only non-approved terminal "
                f"states, got {new_state!r}",
            )
        self._lock_and_reload()
        for request in self:
            if request.state in request._TERMINAL_STATES:
                continue
            old_state = request.state
            request._flip_unsettled_approvers(new_state)
            request._stamp_refusal_metadata(refusal_reason, refusal_note)
            request._cancel_activities()
            request._close_pending_change()
            request._notify_if_terminal_transition(old_state)
            request._log_cycle("terminal", was=old_state, forced=new_state)
            post_kwargs = {"message_type": "notification"}
            if subtype_xmlid:
                post_kwargs["subtype_xmlid"] = subtype_xmlid
            request.message_post(body=body, **post_kwargs)
            if request.state == "refused":
                request._refuse_approval_request()

    def _close_pending_change(self) -> None:
        self.check_singleton()
        if not self.pending_change_field:
            return
        self._get_change_request_activities().sudo().action_feedback()
        self.sudo().write({"pending_change_field": False})

    def _notify_if_terminal_transition(self, old_state: str) -> None:
        self.check_singleton()
        if self.state != old_state and self.state in self._TERMINAL_STATES:
            self._notify_source_document_state_change(self.state)

    def _notify_source_document_state_change(self, new_state: str) -> None:
        self.check_singleton()
        if not self.res_model or not self.res_id:
            return

        try:
            source_doc = self.env[self.res_model].browse(self.res_id)
            mixin_cls = self.env.registry["mixin.approval"]
        except KeyError:
            _logger.debug(
                "Source model %s not in registry; skipping approval state notification",
                self.res_model,
            )
            return
        if not isinstance(source_doc, mixin_cls):
            return
        if source_doc.approval_request_id != self:
            _logger.warning(
                "Approval request %s points at %s#%s but that document does "
                "not reference it back; skipping source notification.",
                self.id,
                self.res_model,
                self.res_id,
            )
            return
        try:
            source_doc.sudo().with_context(
                approval_acting_user_id=self.env.uid,
            )._on_approval_state_changed(new_state)
        except MissingError:
            _logger.debug(
                "Could not notify source document %s#%s of approval state change",
                self.res_model,
                self.res_id,
            )

    _CYCLE_LOG_PREFIX = "approval-cycle"

    def _log_cycle(self, event: str, **details) -> None:
        if not _logger.isEnabledFor(logging.DEBUG):
            return
        self.check_singleton()
        rows = " ".join(
            f"{approver.user_id.login}={approver.state}"
            for approver in self.approver_ids.sorted(lambda a: (a.sequence, a.id))
        )
        extra = "".join(f" {key}={value}" for key, value in details.items())
        _logger.debug(
            "%s %s request=%s (%s) state=%s minimum=%s rows=[%s]%s",
            self._CYCLE_LOG_PREFIX,
            event,
            self.id,
            self.name or "draft",
            self.state,
            self.approval_minimum,
            rows,
            extra,
        )

    def _update_next_approvers_state(
        self,
        approver: models.BaseModel,
        new_state: str,
        only_next_approver: bool,
        cancel_activities: bool = False,
    ) -> None:
        approvers_updated = self.env["approval.approver"]
        for approval in self.filtered("approve_sequentially"):
            current_approver = approval.approver_ids & approver
            if not current_approver:
                continue
            anchor = min(
                ((a.sequence, a.id) for a in current_approver),
            )
            settled = approval.approver_ids._SETTLED_STATES
            approvers_to_update = approval.approver_ids.filtered(
                lambda a, anchor=anchor, settled=settled: (
                    a.state not in settled and (a.sequence, a.id) > anchor
                ),
            ).sorted(lambda a: (a.sequence, a.id))
            if only_next_approver and approvers_to_update:
                approvers_to_update = approvers_to_update[0]
            approvers_updated |= approvers_to_update
        approvers_updated.sudo().state = new_state
        if new_state == "pending":
            approvers_updated._create_activity()
        if cancel_activities:
            approvers_updated.request_id._cancel_activities()

import logging
from typing import Any

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import Command, Domain

from .approval_utils import boolean_search_domain, is_approval_manager

_logger = logging.getLogger(__name__)


class ApprovalRequestAction(models.Model):
    _inherit = "approval.request"

    @api.model
    def _search_is_overdue(
        self,
        operator: str,
        value: Any,
    ) -> list[tuple[str, str, Any]]:
        now = fields.Datetime.now()
        return boolean_search_domain(
            operator,
            value,
            true_domain=[
                ("approval_deadline", "!=", False),
                ("approval_deadline", "<", now),
                ("state", "=", "pending"),
            ],
            false_domain=[
                "|",
                "|",
                ("approval_deadline", "=", False),
                ("approval_deadline", ">=", now),
                ("state", "!=", "pending"),
            ],
        )

    @api.onchange("category_id")
    def _onchange_category_autofill(self) -> None:
        if not self.category_id:
            return

        last_request = self._recent_approved_by_owner(limit=1)

        if not last_request:
            return

        if self.category_id.has_location == "required" and not self.location:
            self.location = last_request.location

        if self.category_id.has_partner == "required" and not self.partner_id:
            self.partner_id = last_request.partner_id

        if self.category_id.has_reference == "required" and not self.reference:
            self.reference = last_request.reference

    def _action_bulk_decision(
        self,
        action_method: str,
        action_label: str,
        past_tense: str,
    ) -> dict[str, Any]:
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

        success_count = 0
        failed_requests = []
        for request in self:
            try:
                with self.env.cr.savepoint():
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

    def _get_current_pending_approver(
        self, user: models.BaseModel | None = None
    ) -> models.BaseModel:
        self.ensure_one()
        user = user or self.env.user
        return self.approver_ids.filtered(
            lambda a: a.state == "pending" and a._get_effective_approver() == user,
        )

    def _raise_not_assigned_approver(self) -> None:
        raise UserError(
            self.env._(
                "You are not assigned as an approver for this request, "
                "or your approval has already been processed.",
            ),
        )

    def _check_decision_actor(self, approver: models.BaseModel) -> None:
        if self.env.su or is_approval_manager(self.env):
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

    def _apply_decision(
        self,
        decision: str,
        approver: models.BaseModel | None = None,
    ) -> None:
        self.ensure_one()
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
                self.approver_ids.sudo().filtered(
                    lambda a: a.state not in self._TERMINAL_STATES,
                ).write({"state": "refused"})
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
        self.ensure_one()
        self._check_no_pending_change("approve")
        self._apply_decision("approve", approver)

    def _refuse_cascade(self) -> bool:
        self.ensure_one()
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
        self.ensure_one()
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
        self.ensure_one()

        self._check_change_request_allowed()

        if approver is None and not self.env.context.get("skip_wizard"):
            return self._get_decision_wizard_action("change")

        if not isinstance(approver, models.BaseModel):
            approver = self._get_current_pending_approver()
        else:
            approver = approver.filtered(
                lambda a: a.request_id == self and a.state == "pending",
            )
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
        return None

    def action_resubmit(self) -> None:
        self.ensure_one()
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

    def action_refuse_bulk(self) -> dict[str, Any]:
        return self._action_bulk_decision("action_refuse", "refusal", "refused")

    def action_refuse(
        self, approver: models.BaseModel | None = None
    ) -> dict[str, Any] | None:
        self.ensure_one()
        self._check_no_pending_change("refuse")

        if approver is None and not self.env.context.get("skip_wizard"):
            return self._get_decision_wizard_action("refuse")

        self._apply_decision("refuse", approver)
        return None

    def _get_decision_wizard_action(self, decision_type: str) -> dict[str, Any]:
        self.ensure_one()
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

    def action_view_attachment(self) -> dict[str, Any]:
        self.ensure_one()
        res = self.env["ir.actions.act_window"]._get_action_dict_by_xml_id(
            "base.action_attachment"
        )
        res["domain"] = [
            ("res_model", "=", "approval.request"),
            ("res_id", "in", self.ids),
        ]
        res["context"] = {
            "default_res_model": "approval.request",
            "default_res_id": self.id,
        }
        return res

    @api.model
    def _get_domain_pending_review(self, user: models.BaseModel) -> list:
        return [
            ("state", "=", "pending"),
            "|",
            (
                "approver_ids",
                "any",
                [
                    ("user_id", "=", user.id),
                    ("is_delegated", "=", False),
                    ("state", "=", "pending"),
                ],
            ),
            (
                "approver_ids",
                "any",
                [
                    ("delegate_id", "=", user.id),
                    ("is_delegated", "=", True),
                    ("state", "=", "pending"),
                ],
            ),
        ]

    @api.model
    def _search_is_pending_my_review(self, operator: str, value: Any) -> Domain:
        awaiting = Domain(self._get_domain_pending_review(self.env.user))
        return boolean_search_domain(operator, value, awaiting, ~awaiting)

    @api.model
    def action_view_to_review(self) -> dict[str, Any]:
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Approvals to Review"),
            "res_model": "approval.request",
            "view_mode": "list,kanban,form",
            "domain": self._get_domain_pending_review(self.env.user),
            "context": {},
        }

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

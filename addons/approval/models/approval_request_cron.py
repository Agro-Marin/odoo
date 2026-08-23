import logging
from datetime import timedelta

from odoo import api, fields, models
from odoo.fields import Domain

_logger = logging.getLogger(__name__)

CRON_BATCH_LIMIT = 500


class ApprovalRequestCron(models.Model):
    _inherit = "approval.request"

    @api.model
    def cron_smart_escalation(self) -> int:
        now = fields.Datetime.now()
        reminders_sent = 0

        self._reconcile_delegation_activities()

        for priority, rules in self._get_escalation_rules().items():
            reminder_threshold = now - timedelta(hours=rules["first_reminder"])
            escalation_threshold = now - timedelta(hours=rules["escalation"])

            domain = [
                ("state", "=", "pending"),
                ("priority", "=", priority),
                ("pending_change_field", "=", False),
                "|",
                ("last_reminder_date", "=", False),
                ("last_reminder_date", "<", reminder_threshold),
                ("date_confirmed", "<", reminder_threshold),
            ]

            # One query per ESCALATION_RULES entry, not per record: the loop is
            # over the priority selection, so the count is fixed and independent
            # of the data. Each priority carries its own reminder threshold and
            # its own CRON_BATCH_LIMIT, which one merged query cannot preserve.
            requests_to_remind = self.search(  # pylint: disable=n-plus-one-query
                domain,
                order="date_confirmed asc",
                limit=CRON_BATCH_LIMIT,
            )

            acknowledged_by_count: dict[int, list[int]] = {}

            for request in requests_to_remind:
                try:
                    with self.env.cr.savepoint():
                        did_work = self._escalate_or_remind_one(
                            request, escalation_threshold
                        )
                except Exception:
                    _logger.exception(
                        "Smart escalation failed for request %s; skipping.",
                        request.id,
                    )
                    continue

                if not did_work:
                    continue

                acknowledged_by_count.setdefault(
                    request.reminder_count,
                    [],
                ).append(request.id)
                reminders_sent += 1

            for prior_count, ids in acknowledged_by_count.items():
                self.browse(ids).sudo().write(
                    {
                        "last_reminder_date": now,
                        "reminder_count": prior_count + 1,
                    }
                )

        if reminders_sent:
            _logger.info("Smart escalation: Sent %s reminders", reminders_sent)

        return reminders_sent

    def _escalate_or_remind_one(self, request, escalation_threshold) -> int:
        has_stalled_approver = any(
            not a._get_effective_approver().active
            for a in request.approver_ids
            if a.state == "pending"
        )
        needs_escalation = has_stalled_approver or (
            request.date_confirmed < escalation_threshold
            and not request.escalated_to_manager
        )
        if not needs_escalation:
            return request._send_reminder()
        did_work = request._escalate_to_manager()
        _by_manager, not_escalated = request._resolve_escalation_targets()
        if not_escalated:
            did_work = request._send_reminder(not_escalated) or did_work
        return did_work

    @api.model
    def _reconcile_delegation_activities(self) -> None:
        activity_type = self.env.ref("approval.mail_activity_data_approval")
        pending_approvers = self.env["approval.approver"].search(
            [
                ("state", "=", "pending"),
                ("request_id.state", "=", "pending"),
                ("delegate_id", "!=", False),
            ],
            order="id",
            limit=CRON_BATCH_LIMIT,
        )
        for approver in pending_approvers:
            request = approver.request_id
            effective = approver._get_effective_approver()
            correct = request.activity_ids.filtered(
                lambda a, u=effective, t=activity_type: (
                    a.user_id == u and a.activity_type_id == t
                ),
            )
            stale = request.activity_ids.filtered(
                lambda a, u=effective, t=activity_type, ap=approver: (
                    a.activity_type_id == t
                    and a.user_id != u
                    and a.user_id in (ap.user_id | ap.delegate_id)
                ),
            )
            if not stale:
                continue
            try:
                with self.env.cr.savepoint():
                    if correct:
                        stale.action_feedback()
                    else:
                        stale[:1].sudo().write({"user_id": effective.id})
                        stale[1:].action_feedback()
            except Exception:
                _logger.exception(
                    "Delegation activity reconciliation failed for "
                    "approver %s; skipping.",
                    approver.id,
                )

    @api.model
    def cron_auto_expire(self) -> None:
        expired_requests, hours_by_category = self._eligible_by_category_domain(
            "auto_expire_hours",
        )
        if not expired_requests:
            return

        expired_count = 0
        for request in expired_requests:
            body = self.env._(
                "This request was automatically cancelled after exceeding "
                "the %(hours)d-hour expiration window.",
                hours=hours_by_category[request.category_id.id],
            )
            try:
                with self.env.cr.savepoint():
                    request._force_terminal(
                        "cancelled",
                        body=body,
                        subtype_xmlid="mail.mt_note",
                    )
                expired_count += 1
            except Exception:
                _logger.exception(
                    "Auto-expire failed for request %s; skipping.",
                    request.id,
                )

        if expired_count:
            _logger.info("Auto-expire: Cancelled %d expired requests", expired_count)

    @api.model
    def _eligible_by_category_domain(
        self,
        hours_field: str,
        extra_domain=None,
        category_domain=None,
    ):
        categories = self.env["approval.category"].search(
            Domain([(hours_field, ">", 0)]) & Domain(category_domain or []),
        )
        if not categories:
            return self.browse(), {}

        now = fields.Datetime.now()
        hours_by_category = {c.id: c[hours_field] for c in categories}
        windows = Domain.FALSE
        for category in categories:
            windows |= Domain(
                [
                    ("category_id", "=", category.id),
                    (
                        "date_confirmed",
                        "<=",
                        now - timedelta(hours=hours_by_category[category.id]),
                    ),
                ],
            )
        domain = Domain([("state", "=", "pending")]) & windows
        if extra_domain:
            domain &= Domain(extra_domain)
        requests = self.search(
            domain,
            order="date_confirmed asc",
            limit=CRON_BATCH_LIMIT,
        )
        return requests, hours_by_category

    @api.model
    def cron_consent_approval(self) -> None:
        eligible, _hours = self._eligible_by_category_domain(
            "consent_approval_hours",
            extra_domain=[("pending_change_field", "=", False)],
            category_domain=[("approve_sequentially", "=", False)],
        )
        consent_count = 0
        for request in eligible:
            try:
                with self.env.cr.savepoint():
                    if self._consent_approve_one(request, request.category_id):
                        consent_count += 1
            except Exception:
                _logger.exception(
                    "Consent approval failed for request %s; skipping.",
                    request.id,
                )

        if consent_count:
            _logger.info(
                "Consent approval: Auto-approved %d requests",
                consent_count,
            )

    def _consent_approve_one(self, request, category) -> bool:
        if not request._can_consent_approve():
            return False

        request._lock_and_reload(with_approvers=True)
        if request.state != "pending":
            return False

        pending = request.approver_ids.filtered(lambda a: a.state == "pending")
        if not pending:
            return False

        old_state = request.state
        pending.sudo().write({"state": "approved"})
        request._cancel_activities()
        request._notify_if_terminal_transition(old_state)
        request.message_post(
            body=self.env._(
                "Auto-approved by consent: no objection received "
                "within %(hours)d-hour window.",
                hours=category.consent_approval_hours,
            ),
            message_type="notification",
            subtype_xmlid="mail.mt_note",
        )
        return True

    def _can_consent_approve(self) -> bool:
        self.ensure_one()
        return True

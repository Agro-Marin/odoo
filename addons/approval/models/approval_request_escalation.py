import logging
from typing import Any

from markupsafe import Markup

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class ApprovalRequestEscalation(models.Model):
    _inherit = "approval.request"

    def _get_escalation_manager(self, approver) -> Any:
        category = self.category_id
        if (
            category.escalate_overdue
            and category.escalation_user_id
            and category.escalation_user_id.active
        ):
            return category.escalation_user_id
        return self._get_default_escalation_manager()

    def _get_default_escalation_manager(self) -> Any:
        cache = self.env.cr.cache.setdefault("approval_default_escalation_manager", {})
        company_id = self.company_id.id
        if company_id not in cache:
            group = self.env.ref(
                "approval.group_approval_manager", raise_if_not_found=False
            )
            cache[company_id] = (
                self.env["res.users"]
                .search(
                    [
                        ("all_group_ids", "in", group.id),
                        ("company_ids", "in", company_id),
                        ("active", "=", True),
                    ],
                    order="id",
                    limit=1,
                )
                .id
                if group
                else False
            )
        return self.env["res.users"].browse(cache[company_id] or ())

    @api.model
    def _invalidate_escalation_manager_cache(self) -> None:
        self.env.cr.cache.pop("approval_default_escalation_manager", None)

    def _resolve_escalation_targets(self) -> tuple[dict, models.BaseModel]:
        self.check_singleton()
        by_manager: dict = {}
        unescalated = self.env["approval.approver"]
        for approver in self.approver_ids.filtered(lambda a: a.state == "pending"):
            manager = self._get_escalation_manager(approver)
            if manager:
                by_manager.setdefault(manager, self.env["approval.approver"])
                by_manager[manager] |= approver
            else:
                unescalated |= approver
        return by_manager, unescalated

    def _escalate_to_manager(self) -> int:
        self.check_singleton()
        by_manager, _unescalated = self._resolve_escalation_targets()
        if not by_manager:
            return 0

        priority_label = dict(self._fields["priority"].selection)[self.priority]
        for manager, approvers in by_manager.items():
            self.message_post(
                # The markup is the template and the values are its arguments:
                # a translated str carrying tags is escaped by message_post and
                # reaches the reader as visible source.
                body=Markup(
                    self.env._(
                        "<p><strong>Escalation Notice</strong></p>"
                        "<p>Approval request <strong>%(name)s</strong> has been pending for %(duration)s.</p>"
                        "<ul>"
                        "<li><strong>Priority:</strong> %(priority)s</li>"
                        "<li><strong>Assigned approver(s):</strong> %(approver)s</li>"
                        "<li><strong>Reminders sent:</strong> %(count)d</li>"
                        "</ul>"
                        "<p>Please follow up.</p>"
                    )
                )
                % {
                    "name": self.name,
                    "duration": self._get_pending_duration(),
                    "priority": priority_label,
                    "approver": ", ".join(sorted(approvers.user_id.mapped("name"))),
                    "count": self.reminder_count,
                },
                subject=self.env._(
                    "Escalation: Overdue Approval - %(name)s", name=self.name
                ),
                partner_ids=manager.partner_id.ids,
                subtype_xmlid="mail.mt_note",
            )

        self.sudo().escalated_to_manager = True
        return len(by_manager)

    def _get_pending_duration(self) -> str:
        self.check_singleton()
        if not self.date_confirmed:
            return self.env._("Unknown")

        delta = fields.Datetime.now() - self.date_confirmed
        days = delta.days
        hours = delta.seconds // 3600

        if days > 0:
            return self.env._("%(count)d day(s)", count=days)
        return self.env._("%(count)d hour(s)", count=hours)

    @api.model
    def _get_escalation_rules(self) -> dict[str, dict[str, int]]:
        icp = self.env["ir.config_parameter"].sudo()
        rules = {p: dict(kinds) for p, kinds in self.ESCALATION_RULES.items()}
        for priority, kinds in rules.items():
            for kind in kinds:
                param = icp.get_param(f"approval.escalation.{priority}.{kind}")
                if not param:
                    continue
                try:
                    kinds[kind] = int(param)
                except ValueError:
                    _logger.warning(
                        "Ignoring invalid approval.escalation.%s.%s = %r",
                        priority,
                        kind,
                        param,
                    )
        return rules

    def _send_reminder(self, approvers: models.BaseModel | None = None) -> int:
        self.check_singleton()
        pending_approvers = (
            approvers
            if approvers is not None
            else self.approver_ids.filtered(lambda a: a.state == "pending")
        )

        priority_label = dict(self._fields["priority"].selection)[self.priority]
        activity_type = self.env.ref("approval.mail_activity_data_approval")
        reminded = 0

        for approver in pending_approvers:
            effective_user = approver._get_effective_approver()

            if not effective_user.active:
                continue

            existing_activity = self.activity_ids.filtered(
                lambda a, user=effective_user, atype=activity_type: (
                    a.user_id == user and a.activity_type_id == atype
                ),
            )

            reminder_note = self.env._(
                "<p><strong>Priority:</strong> %(priority)s</p>"
                "<p>This approval has been pending for %(duration)s.</p>"
                "<p><strong>Reminders sent:</strong> %(count)d</p>",
                priority=priority_label,
                duration=self._get_pending_duration(),
                count=self.reminder_count,
            )

            if existing_activity:
                existing_activity[:1].write(
                    {
                        "summary": self.env._(
                            "Approval Reminder: %(name)s", name=self.name
                        ),
                        "note": reminder_note,
                        "date_deadline": fields.Date.today(),
                    },
                )
            else:
                self.activity_schedule(
                    "approval.mail_activity_data_approval",
                    user_id=effective_user.id,
                    summary=self.env._("Approval Reminder: %(name)s", name=self.name),
                    note=reminder_note,
                )
            reminded += 1

        return reminded

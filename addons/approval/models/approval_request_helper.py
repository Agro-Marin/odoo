import logging
import time
from typing import Any

from odoo import api, fields, models
from odoo.exceptions import MissingError

_logger = logging.getLogger(__name__)


class ApprovalRequestHelper(models.Model):
    _inherit = "approval.request"

    def _prepare_category_snapshot(self) -> dict[str, Any]:
        self.ensure_one()
        cat = self.category_id
        replacement = self._find_matching_replacement()
        snapshot: dict[str, Any] = {
            "category_name": cat.name,
            "approval_minimum": cat.approval_minimum,
            "approval_type": cat.approval_type,
            "approve_sequentially": cat.approve_sequentially,
            "group_approval": cat.group_approval,
            "approval_deadline_hours": cat.approval_deadline_hours,
            "approvers": [
                {
                    "user_id": a.user_id.id,
                    "user_name": a.user_id.name,
                    "required": a.required,
                    "sequence": a.sequence,
                }
                for a in cat.approver_ids
            ],
            "rules": [
                {
                    "name": r.name,
                    "condition_field": r.condition_field,
                    "operator": r.operator,
                    "threshold": r.threshold,
                    "action_type": r.action_type,
                }
                for r in cat.rule_ids.filtered("active")
            ],
            "effective_approval_minimum": self.approval_minimum,
            "effective_approvers": [
                {
                    "user_id": a.user_id.id,
                    "user_name": a.user_id.name,
                    "required": a.required,
                    "sequence": a.sequence,
                }
                for a in self.approver_ids
            ],
        }
        if replacement:
            snapshot["replacement_rule"] = {
                "id": replacement.id,
                "name": replacement.name,
                "condition_field": replacement.condition_field,
                "operator": replacement.operator,
                "threshold": replacement.threshold,
                "threshold_max": replacement.threshold_max,
                "approval_minimum": replacement.approval_minimum,
            }
        return snapshot

    def _label(self) -> str:
        self.ensure_one()
        return self.name or self.category_id.name

    def _cancel_activities(self) -> None:
        approval_activity = self.env.ref("approval.mail_activity_data_approval")
        activities = self.activity_ids.filtered(
            lambda a: a.activity_type_id == approval_activity,
        )
        activities.sudo().unlink()

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
        self.ensure_one()
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
        self.ensure_one()
        by_manager, _unescalated = self._resolve_escalation_targets()
        if not by_manager:
            return 0

        priority_label = dict(self._fields["priority"].selection)[self.priority]
        for manager, approvers in by_manager.items():
            self.message_post(
                body=self.env._(
                    "<p><strong>Escalation Notice</strong></p>"
                    "<p>Approval request <strong>%(name)s</strong> has been pending for %(duration)s.</p>"
                    "<ul>"
                    "<li><strong>Priority:</strong> %(priority)s</li>"
                    "<li><strong>Assigned approver(s):</strong> %(approver)s</li>"
                    "<li><strong>Reminders sent:</strong> %(count)d</li>"
                    "</ul>"
                    "<p>Please follow up.</p>",
                    name=self.name,
                    duration=self._get_pending_duration(),
                    priority=priority_label,
                    approver=", ".join(sorted(approvers.user_id.mapped("name"))),
                    count=self.reminder_count,
                ),
                subject=self.env._(
                    "Escalation: Overdue Approval - %(name)s", name=self.name
                ),
                partner_ids=manager.partner_id.ids,
                subtype_xmlid="mail.mt_note",
            )

        self.sudo().escalated_to_manager = True
        return len(by_manager)

    def _matched_add_approver_rules(self):
        self.ensure_one()
        return self.category_id.rule_ids.filtered(
            lambda r: (
                r.active
                and r.action_type == "add_approver"
                and self._rule_applies_to_company(r)
                and r._evaluate(self)
            ),
        )

    def _get_additional_approvers(self) -> list[tuple[int, bool, int]]:
        self.ensure_one()
        result: list[tuple[int, bool, int]] = []
        for rule in self._matched_add_approver_rules():
            result.extend(rule._get_approver_tuples())
        return result

    def _applied_rule_ids_after_sync(self, matched_rules):
        self.ensure_one()
        preserved = self.applied_rule_ids.filtered(
            lambda r: r.action_type != "add_approver",
        )
        return preserved | matched_rules

    def _matched_add_approver_rule_by_user(self, matched_rules=None) -> dict[int, int]:
        self.ensure_one()
        if matched_rules is None:
            matched_rules = self._matched_add_approver_rules()
        mapping: dict[int, int] = {}
        for rule in matched_rules:
            for user in rule.approver_ids:
                mapping.setdefault(user.id, rule.id)
        return mapping

    def _get_managed_approver_user_ids(
        self,
        replacement=None,
        matched_rules=None,
    ) -> set[int]:
        self.ensure_one()
        managed = set(self.category_id.approver_ids.user_id.ids)
        if replacement:
            managed.update(replacement.approver_ids.ids)
        for rule in matched_rules or ():
            managed.update(rule.approver_ids.ids)
        if self.group_approval != "no" and self.approver_group_id:
            managed.update(self.approver_group_id.all_user_ids.ids)
        return managed

    def _rule_applies_to_company(self, rule) -> bool:
        self.ensure_one()
        rule_company = rule.company_id
        return not rule_company or rule_company == self.company_id

    def _find_matching_replacement(self):
        self.ensure_one()
        candidates = self.category_id.rule_ids.filtered(
            lambda r: (
                r.active
                and r.action_type == "set_approvers"
                and self._rule_applies_to_company(r)
            ),
        )
        if not candidates:
            return False

        negative_fields = set()
        for rule in candidates.sorted(lambda r: (r.sequence, r.id)):
            value = rule._get_field_value(self)
            if value is None:
                continue
            if rule._compare(value, rule.threshold):
                return rule
            if value < 0:
                negative_fields.add(rule.condition_field)

        if negative_fields:
            _logger.warning(
                "Request %s: no approver-replacing rule matched (negative "
                "%s) — falling back to category '%s' default approvers.",
                self.id or "(new)",
                ", ".join(sorted(negative_fields)),
                self.category_id.name,
            )
        return False

    def _check_auto_action_rules(self) -> bool:
        self.ensure_one()
        rules = self.category_id.rule_ids.filtered(
            lambda r: (
                r.active
                and r.action_type in ("auto_approve", "auto_refuse")
                and self._rule_applies_to_company(r)
            ),
        )
        matching = rules.filtered(lambda r: r._evaluate(self))
        if not matching:
            return False
        rule = self._resolve_auto_action(matching)
        if rule:
            if rule.action_type == "auto_approve":
                self.approver_ids.sudo().write({"state": "approved"})
                self.message_post(
                    body=self.env._(
                        "Auto-approved by rule: %(rule)s "
                        "(%(field)s %(op)s %(threshold)s)",
                        rule=rule.name,
                        field=rule.condition_field,
                        op=rule.operator,
                        threshold=rule.threshold,
                    ),
                    message_type="notification",
                )
                self.applied_rule_ids |= rule
                return True

            if rule.action_type == "auto_refuse":
                self._flip_non_terminal_approvers("refused")
                self._stamp_refusal_metadata(
                    self.env.ref("approval.refusal_reason_auto_rule"),
                    self.env._(
                        "Automatically refused by rule '%(rule)s'.",
                        rule=rule.name,
                    ),
                )
                self._cancel_activities()
                self.message_post(
                    body=self.env._(
                        "Auto-refused by rule: %(rule)s "
                        "(%(field)s %(op)s %(threshold)s)",
                        rule=rule.name,
                        field=rule.condition_field,
                        op=rule.operator,
                        threshold=rule.threshold,
                    ),
                    message_type="notification",
                )
                self.applied_rule_ids |= rule
                if self.state == "refused":
                    self._refuse_approval_request()
                return True

        return False

    def _resolve_auto_action(self, matching_rules):
        refusals = matching_rules.filtered(
            lambda r: r.action_type == "auto_refuse",
        )
        candidates = refusals or matching_rules
        return candidates.sorted(lambda r: (r.sequence, r.id))[:1]

    def _get_pending_duration(self) -> str:
        self.ensure_one()
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

    def _get_sequence_param(self, kind: str, default: int) -> int:
        raw = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param(f"approval.sequence.{kind}", default)
        )
        try:
            return int(raw)
        except TypeError, ValueError:
            _logger.warning(
                "Ignoring invalid approval.sequence.%s = %r; using %d.",
                kind,
                raw,
                default,
            )
            return default

    def _get_sequence_group(self) -> int:
        return self._get_sequence_param("group", 500)

    def _get_sequence_manager(self) -> int:
        return self._get_sequence_param("manager", 9)

    def _get_sequence_manual(self) -> int:
        return self._get_sequence_param("manual", 1000)

    def _get_sequence_replacement(self) -> int:
        return self._get_sequence_param("tier", 10)

    def get_source_document(self) -> Any:
        self.ensure_one()
        if not self.res_model:
            return False
        try:
            if self.res_id:
                return self.env[self.res_model].browse(self.res_id)
            return self.env[self.res_model]
        except KeyError:
            _logger.warning(
                "Source model %s not found for approval request %s",
                self.res_model,
                self.id,
            )
            return False

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

    def _merge_approver_to_staging(
        self,
        staging: dict[int, dict],
        user_id: int,
        required: bool,
        sequence: int,
    ) -> None:
        if user_id in staging:
            staging[user_id]["required"] |= required
            staging[user_id]["sequence"] = min(staging[user_id]["sequence"], sequence)
            staging[user_id]["source_synced"] = True
        else:
            staging[user_id] = {
                "required": required,
                "sequence": sequence,
                "state": "new",
                "source_synced": True,
            }

    _TERMINAL_STATES = frozenset({"approved", "refused", "cancelled"})

    _DECISION_STATES = frozenset({"approved", "refused"})

    @api.model
    def _decision_states_sql(self) -> str:
        members = ", ".join(f"'{state}'" for state in sorted(self._DECISION_STATES))
        return f"({members})"

    def _flip_non_terminal_approvers(self, new_state: str) -> None:
        self.ensure_one()
        self.approver_ids.sudo().filtered(
            lambda a, terminal=self._TERMINAL_STATES: a.state not in terminal,
        ).write({"state": new_state})

    def _stamp_refusal_metadata(
        self,
        refusal_reason: models.BaseModel | None,
        refusal_note: str | None,
    ) -> None:
        self.ensure_one()
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
            request._flip_non_terminal_approvers(new_state)
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
        self.ensure_one()
        if not self.pending_change_field:
            return
        self._get_change_request_activities().sudo().action_feedback()
        self.sudo().write({"pending_change_field": False})

    def _notify_if_terminal_transition(self, old_state: str) -> None:
        self.ensure_one()
        if self.state != old_state and self.state in self._TERMINAL_STATES:
            self._notify_source_document_state_change(self.state)

    def _notify_source_document_state_change(self, new_state: str) -> None:
        self.ensure_one()
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

    def _send_reminder(self, approvers: models.BaseModel | None = None) -> int:
        self.ensure_one()
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

    def _sync_approvers(self) -> None:
        self = self.filtered(lambda r: r.state == "new")
        if not self:
            return
        batch_t0 = time.perf_counter()
        minimum_updates: dict[int, int] = {}
        rows_to_delete: list[int] = []
        rows_to_create: list[dict[str, Any]] = []
        rows_to_update: dict[tuple, list[int]] = {}

        self.category_id.fetch(["rule_ids", "approver_ids"])

        group_sequence = self._get_sequence_group()
        manual_sequence = self._get_sequence_manual()

        for request in self:
            (
                approver_staging,
                users_to_approver,
                duplicate_approvers_to_delete,
                replacement,
                matched_rules,
                superseded_delegations,
            ) = request._compute_desired_approvers(
                group_sequence,
                manual_sequence,
            )

            if superseded_delegations:
                request._retire_superseded_delegations(superseded_delegations)

            desired_applied = request._applied_rule_ids_after_sync(matched_rules)
            if desired_applied != request.applied_rule_ids:
                request.applied_rule_ids = desired_applied

            rows_to_delete.extend(
                dup_approver.id for dup_approver in duplicate_approvers_to_delete
            )

            for user_id, vals in approver_staging.items():
                if user_id not in users_to_approver:
                    rows_to_create.append(
                        {
                            "request_id": request.id,
                            "user_id": user_id,
                            "state": vals["state"],
                            "required": vals["required"],
                            "sequence": vals["sequence"],
                            "source_rule_id": vals.get("source_rule_id"),
                            "source_synced": vals.get("source_synced", True),
                        },
                    )
                else:
                    existing_approver = users_to_approver.pop(user_id)
                    self._stage_approver_update(
                        existing_approver,
                        rows_to_update,
                        vals["required"],
                        vals["sequence"],
                        vals.get("source_rule_id"),
                        vals.get("source_synced", True),
                    )

            rows_to_delete.extend(
                current_approver.id for current_approver in users_to_approver.values()
            )

            effective_minimum = (
                replacement.approval_minimum
                if replacement
                else request.category_id.approval_minimum
            )
            if request.approval_minimum != effective_minimum:
                minimum_updates[request.id] = effective_minimum

        plan = self._prepare_sync_plan(rows_to_delete, rows_to_create, rows_to_update)
        if _logger.isEnabledFor(logging.DEBUG):
            self._log_sync_plan(plan)
        self._execute_sync_plan(plan)

        if minimum_updates:
            by_minimum: dict[int, list[int]] = {}
            for rid, minimum in minimum_updates.items():
                by_minimum.setdefault(minimum, []).append(rid)
            for minimum, ids in by_minimum.items():
                self.browse(ids).sudo().write({"approval_minimum": minimum})

        batch_ms = (time.perf_counter() - batch_t0) * 1000
        if batch_ms > 100 * len(self):
            _logger.warning(
                "Slow approver sync: %d request(s) took %.1fms total",
                len(self),
                batch_ms,
            )

    def _extend_approvers_live(self) -> models.BaseModel:
        live = self.filtered(
            lambda r: r.state == "pending" and not r.pending_change_field,
        )
        if not live:
            return self.env["approval.approver"]

        live.category_id.fetch(["rule_ids", "approver_ids"])
        group_sequence = self._get_sequence_group()
        manual_sequence = self._get_sequence_manual()

        added = self.env["approval.approver"]
        for request in live:
            request._lock_and_reload()
            if request.state != "pending" or request.pending_change_field:
                continue
            added |= request._extend_approvers_live_one(
                group_sequence,
                manual_sequence,
            )
        return added

    def _extend_approvers_live_one(
        self,
        group_sequence: int,
        manual_sequence: int,
    ) -> models.BaseModel:
        self.ensure_one()
        (
            approver_staging,
            users_to_approver,
            _duplicate_approvers,
            replacement,
            matched_rules,
            superseded_delegations,
        ) = self._compute_desired_approvers(group_sequence, manual_sequence)

        missing = {
            user_id: vals
            for user_id, vals in approver_staging.items()
            if user_id not in users_to_approver and vals.get("source_rule_id")
        }
        kept_orphans = [
            approver
            for user_id, approver in users_to_approver.items()
            if user_id not in approver_staging
        ]
        if kept_orphans:
            _logger.info(
                "%s live: request %s keeps %d approver row(s) whose source "
                "no longer matches (%s) -- an approver already asked is never "
                "un-asked.",
                self._SYNC_LOG_PREFIX,
                self.id,
                len(kept_orphans),
                ", ".join(sorted(a.user_id.login for a in kept_orphans)),
            )

        self._raise_approval_minimum_live(replacement)

        if not missing:
            return self.env["approval.approver"]

        if superseded_delegations:
            self._retire_superseded_delegations(superseded_delegations)

        created = self._create_live_approver_rows(missing)
        created.filtered(lambda a: a.state == "pending")._create_activity()
        if matched_rules:
            self.sudo().applied_rule_ids |= matched_rules

        self.message_post(
            body=self.env._(
                "Approver(s) added because the request changed: %(names)s.\n\n"
                "The routing configured on category '%(category)s' now asks "
                "for them. Approvals already given stand.",
                names=", ".join(sorted(created.user_id.mapped("name"))),
                category=self.category_id.name,
            ),
            message_type="notification",
        )
        self._log_cycle("reroute", added=len(created))
        return created

    def _create_live_approver_rows(self, missing: dict[int, dict]):
        self.ensure_one()
        sequential = self.approve_sequentially
        anchor_sequence = min(
            (
                approver.sequence
                for approver in self.approver_ids
                if approver.state == "pending"
            ),
            default=0,
        )
        rows = [
            {
                "request_id": self.id,
                "user_id": user_id,
                "state": "waiting" if sequential else "pending",
                "required": vals["required"],
                "sequence": (
                    max(vals["sequence"], anchor_sequence)
                    if sequential
                    else vals["sequence"]
                ),
                "source_rule_id": vals.get("source_rule_id"),
                "source_synced": vals.get("source_synced", True),
            }
            for user_id, vals in sorted(
                missing.items(),
                key=lambda item: (item[1]["sequence"], item[0]),
            )
        ]
        return (
            self.env["approval.approver"]
            .sudo()
            .with_context(approver_ids_computation=True)
            .create(rows)
        )

    def _raise_approval_minimum_live(self, replacement) -> None:
        self.ensure_one()
        if not replacement:
            return
        if replacement.approval_minimum > self.approval_minimum:
            self.sudo().write({"approval_minimum": replacement.approval_minimum})

    _SYNC_LOG_PREFIX = "approver-sync"

    _CYCLE_LOG_PREFIX = "approval-cycle"

    def _log_cycle(self, event: str, **details) -> None:
        if not _logger.isEnabledFor(logging.DEBUG):
            return
        self.ensure_one()
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

    def _prepare_sync_plan(
        self,
        rows_to_delete: list[int],
        rows_to_create: list[dict[str, Any]],
        rows_to_update: dict[tuple, list[int]],
    ) -> list[tuple]:
        plan: list[tuple] = []
        if rows_to_delete:
            plan.append(("delete", rows_to_delete))
        if rows_to_create:
            plan.append(("create", rows_to_create))
        for update_vals, approver_ids in rows_to_update.items():
            plan.append(("update", (update_vals, approver_ids)))
        return plan

    def _execute_sync_plan(self, plan: list[tuple]) -> None:
        if not plan:
            return
        approver_model = (
            self.env["approval.approver"]
            .sudo()
            .with_context(approver_ids_computation=True)
        )
        for kind, payload in plan:
            if kind == "delete":
                approver_model.browse(payload).unlink()
            elif kind == "create":
                approver_model.create(payload)
            else:
                update_vals, approver_ids = payload
                approver_model.browse(approver_ids).write(dict(update_vals))

    def _log_sync_plan(self, plan: list[tuple]) -> None:
        _logger.debug(
            "%s batch: %d request(s) %s",
            self._SYNC_LOG_PREFIX,
            len(self),
            self.ids,
        )
        for step, (kind, payload) in enumerate(plan, start=1):
            if kind == "delete":
                _logger.debug(
                    "%s   %d. delete %d row(s): %s",
                    self._SYNC_LOG_PREFIX,
                    step,
                    len(payload),
                    sorted(payload),
                )
            elif kind == "create":
                _logger.debug(
                    "%s   %d. create %d row(s)",
                    self._SYNC_LOG_PREFIX,
                    step,
                    len(payload),
                )
                for vals in payload:
                    _logger.debug(
                        "%s        req %s -> user %s (seq %s, %s%s)",
                        self._SYNC_LOG_PREFIX,
                        vals["request_id"],
                        vals["user_id"],
                        vals["sequence"],
                        "required" if vals["required"] else "optional",
                        f", rule {vals['source_rule_id']}"
                        if vals.get("source_rule_id")
                        else "",
                    )
            else:
                update_vals, approver_ids = payload
                _logger.debug(
                    "%s   %d. update %d row(s) %s -> %s",
                    self._SYNC_LOG_PREFIX,
                    step,
                    len(approver_ids),
                    sorted(approver_ids),
                    " ".join(f"{key}={value}" for key, value in update_vals),
                )

    def _retire_superseded_delegations(self, rows) -> None:
        self.ensure_one()
        for row in rows:
            delegate = row.delegate_id
            row.sudo().write(
                {
                    "delegate_id": False,
                    "delegate_start_date": False,
                    "delegate_end_date": False,
                },
            )
            self.message_post(
                body=self.env._(
                    "%(principal)s's delegation to %(delegate)s was ended: "
                    "%(delegate)s is now an approver of this request in "
                    "their own right, and one person cannot hold two "
                    "approvals.",
                    principal=row.user_id.name,
                    delegate=delegate.name,
                ),
                message_type="notification",
            )

    def _compute_desired_approvers(
        self,
        group_sequence: int,
        manual_sequence: int,
    ) -> tuple[dict[int, dict], dict[int, Any], list[Any], Any, Any, Any]:
        self.ensure_one()
        users_to_approver: dict[int, Any] = {}
        duplicate_approvers_to_delete: list[Any] = []
        for approver in self.approver_ids:
            user_id = approver.user_id.id
            if user_id in users_to_approver:
                duplicate_approvers_to_delete.append(approver)
            else:
                users_to_approver[user_id] = approver

        approver_staging: dict[int, dict] = {}

        matched_rules = self._matched_add_approver_rules()

        for user_id, required, sequence in self._get_additional_approvers():
            self._merge_approver_to_staging(
                approver_staging, user_id, required, sequence
            )

        replacement = False
        if self.group_approval != "exclusive":
            replacement = self._find_matching_replacement()
            if replacement:
                replacement_sequence = self._get_sequence_replacement()
                for user in replacement.approver_ids:
                    self._merge_approver_to_staging(
                        approver_staging,
                        user.id,
                        replacement.approver_required,
                        replacement_sequence,
                    )
            else:
                for cat_approver in self.category_id.approver_ids:
                    self._merge_approver_to_staging(
                        approver_staging,
                        cat_approver.user_id.id,
                        cat_approver.required,
                        cat_approver.sequence,
                    )

        if self.group_approval != "no" and self.approver_group_id:
            for user in self.approver_group_id.all_user_ids:
                self._merge_approver_to_staging(
                    approver_staging,
                    user.id,
                    False,
                    group_sequence,
                )

        rule_user_to_rule_id = self._matched_add_approver_rule_by_user(matched_rules)
        replacement_user_ids = (
            set(replacement.approver_ids.ids) if replacement else set()
        )
        for user_id, vals in approver_staging.items():
            if user_id in replacement_user_ids:
                vals["source_rule_id"] = replacement.id
            else:
                vals["source_rule_id"] = rule_user_to_rule_id.get(user_id)

        managed_user_ids = self._get_managed_approver_user_ids(
            replacement=replacement,
            matched_rules=matched_rules,
        )
        for user_id, existing_approver in users_to_approver.items():
            if user_id in approver_staging:
                continue
            is_injected_orphan = (
                existing_approver.source_synced
                or existing_approver.source_rule_id
                or user_id in managed_user_ids
            )
            if not is_injected_orphan:
                approver_staging[user_id] = {
                    "state": existing_approver.state,
                    "required": False,
                    "sequence": manual_sequence,
                    "source_rule_id": None,
                    "source_synced": False,
                }

        superseded_delegations = self.approver_ids.filtered(
            lambda a: (
                a.delegate_id
                and a.delegate_id.id in approver_staging
                and a.delegate_id.id != a.user_id.id
            ),
        )

        return (
            approver_staging,
            users_to_approver,
            duplicate_approvers_to_delete,
            replacement,
            matched_rules,
            superseded_delegations,
        )

    @api.model
    def _stage_approver_update(
        self,
        approver: models.BaseModel,
        rows_to_update: dict[tuple, list[int]],
        new_required: bool,
        new_sequence: int,
        new_source_rule_id: int | None = None,
        new_source_synced: bool = True,
    ) -> None:
        if (
            approver.required != new_required
            or approver.sequence != new_sequence
            or approver.source_rule_id.id != (new_source_rule_id or False)
            or approver.source_synced != new_source_synced
        ):
            key = (
                ("required", new_required),
                ("sequence", new_sequence),
                ("source_rule_id", new_source_rule_id),
                ("source_synced", new_source_synced),
            )
            rows_to_update.setdefault(key, []).append(approver.id)

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
            approvers_to_update = approval.approver_ids.filtered(
                lambda a, anchor=anchor: (
                    a.state not in self._TERMINAL_STATES and (a.sequence, a.id) > anchor
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

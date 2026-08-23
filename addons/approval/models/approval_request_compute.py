from collections import Counter
from datetime import timedelta
from typing import Any

from odoo import api, fields, models

from .approval_utils import is_approval_manager


class ApprovalRequestCompute(models.Model):
    _inherit = "approval.request"

    @api.depends("name")
    def _compute_display_name(self) -> None:
        placeholder = self.env._("New")
        for request in self:
            request.display_name = request.name or placeholder

    def _compute_count_attachment(self) -> None:
        domain = [
            ("res_model", "=", "approval.request"),
            ("res_id", "in", self.ids),
        ]
        attachment_data = self.env["ir.attachment"]._read_group(
            domain,
            groupby=["res_id"],
            aggregates=["__count"],
        )
        attachment_counts = dict(attachment_data)
        for request in self:
            request.count_attachment = attachment_counts.get(request.id, 0)

    @api.depends("res_model")
    def _compute_res_model_id(self) -> None:
        for request in self:
            if request.res_model:
                request.res_model_id = self.env["ir.model"]._get(request.res_model)
            else:
                request.res_model_id = False

    @api.depends("res_model", "res_id")
    def _compute_res_name(self) -> None:
        ids_by_model: dict[str, list[int]] = {}
        for request in self:
            if request.res_model and request.res_id:
                ids_by_model.setdefault(request.res_model, []).append(request.res_id)

        names_by_model: dict[str, dict[int, str] | None] = {}
        existing_by_model: dict[str, set[int]] = {}
        for model, ids in ids_by_model.items():
            try:
                records = self.env[model].browse(ids).exists()
            except KeyError:
                names_by_model[model] = None
                continue
            existing_by_model[model] = set(records.ids)
            accessible = records._filtered_access("read")
            names_by_model[model] = {
                record.id: record.display_name for record in accessible
            }

        for request in self:
            if not (request.res_model and request.res_id):
                request.res_name = False
                continue
            names = names_by_model.get(request.res_model)
            if names is None:
                request.res_name = self.env._("Unknown Model")
            elif request.res_id in names:
                request.res_name = names[request.res_id]
            elif request.res_id in existing_by_model.get(request.res_model, ()):
                request.res_name = self.env._("Access Denied")
            else:
                request.res_name = self.env._("Deleted Document")

    @api.depends("date_confirmed", "category_snapshot")
    def _compute_approval_deadline(self) -> None:
        for request in self:
            hours = request._get_snapshot_config("approval_deadline_hours")
            if request.date_confirmed and hours:
                request.approval_deadline = request.date_confirmed + timedelta(
                    hours=hours,
                )
            else:
                request.approval_deadline = False

    def _get_snapshot_config(self, key: str) -> Any:
        self.ensure_one()
        snapshot = self.category_snapshot or {}
        value = snapshot.get(key)
        if value is None:
            value = self.category_id[key]
        return value

    @api.depends("approval_deadline", "state")
    def _compute_is_overdue(self) -> None:
        now = fields.Datetime.now()
        for request in self:
            request.is_overdue = (
                request.approval_deadline
                and request.approval_deadline < now
                and request.state == "pending"
            )

    @api.depends(
        "date_confirmed",
        "state",
        "date_approval_granted",
        "date_refused",
        "date_cancelled",
        "category_id.sla_target_hours",
        "category_id.sla_warning_pct",
    )
    def _compute_sla_status(self) -> None:
        now = fields.Datetime.now()
        for request in self:
            sla_hours = request.category_id.sla_target_hours
            if not sla_hours or not request.date_confirmed:
                request.sla_status = "no_sla"
                continue

            if request.state in self._TERMINAL_STATES:
                resolved_date = {
                    "approved": request.date_approval_granted,
                    "refused": request.date_refused,
                    "cancelled": request.date_cancelled,
                }.get(request.state) or now
                elapsed = (
                    resolved_date - request.date_confirmed
                ).total_seconds() / 3600
                request.sla_status = "met" if elapsed <= sla_hours else "breached"
                continue

            elapsed = (now - request.date_confirmed).total_seconds() / 3600
            request.sla_status = self._sla_status_for(
                elapsed,
                sla_hours,
                request.category_id.sla_warning_pct,
            )

    _SLA_DEFAULT_WARNING_PCT = 80

    @api.model
    def _sla_status_for(
        self,
        elapsed_hours: float,
        sla_hours: float,
        warning_pct: float | None,
    ) -> str:
        if elapsed_hours > sla_hours:
            return "breached"
        warning_hours = sla_hours * (
            (warning_pct or self._SLA_DEFAULT_WARNING_PCT) / 100
        )
        if elapsed_hours > warning_hours:
            return "at_risk"
        return "on_track"

    @api.model
    def _search_sla_status(self, operator: str, value: str | list | None) -> list:
        if operator not in ("=", "!=", "in", "not in"):
            raise NotImplementedError(
                f"Unsupported operator {operator!r} for sla_status"
            )
        wanted = {value} if isinstance(value, str) else set(value or ())
        all_statuses = {s[0] for s in self._fields["sla_status"].selection}
        if operator in ("!=", "not in"):
            wanted = all_statuses - wanted
        self.env["approval.request"].flush_model()
        self.env["approval.category"].flush_model()
        where_sql = ""
        if "no_sla" not in wanted:
            where_sql = (
                "WHERE COALESCE(ac.sla_target_hours, 0) > 0 "
                "AND ar.date_confirmed IS NOT NULL"
            )
        default_warning_pct = self._SLA_DEFAULT_WARNING_PCT
        self.env.cr.execute(
            f"""
            SELECT id FROM (
            SELECT ar.id,
                   CASE
                       WHEN COALESCE(ac.sla_target_hours, 0) = 0
                            OR ar.date_confirmed IS NULL
                           THEN 'no_sla'
                       WHEN ar.state IN ('approved', 'refused', 'cancelled')
                           THEN CASE
                               -- Keyed on the CURRENT state's date
                               -- (mirrors _compute_sla_status). Since
                               -- 19.0.1.0.22 the stamps are cleared when
                               -- the request leaves the state they
                               -- record, so only one is ever set; the
                               -- COALESCE stays as a guard for rows
                               -- written before that.
                               WHEN COALESCE(
                                       CASE ar.state
                                           WHEN 'approved' THEN ar.date_approval_granted
                                           WHEN 'refused' THEN ar.date_refused
                                           WHEN 'cancelled' THEN ar.date_cancelled
                                       END,
                                       NOW() AT TIME ZONE 'UTC')
                                    <= ar.date_confirmed
                                       + ac.sla_target_hours * INTERVAL '1 hour'
                                   THEN 'met'
                               ELSE 'breached'
                           END
                       WHEN NOW() AT TIME ZONE 'UTC'
                            > ar.date_confirmed
                              + ac.sla_target_hours * INTERVAL '1 hour'
                           THEN 'breached'
                       WHEN NOW() AT TIME ZONE 'UTC'
                            > ar.date_confirmed
                              + ac.sla_target_hours
                                * COALESCE(
                                      NULLIF(ac.sla_warning_pct, 0),
                                      {default_warning_pct}
                                  )
                                / 100.0 * INTERVAL '1 hour'
                           THEN 'at_risk'
                       ELSE 'on_track'
                   END AS status
            FROM approval_request ar
            JOIN approval_category ac ON ac.id = ar.category_id
            {where_sql}
            ) AS classified
            WHERE status = ANY(%s)
            """,
            [sorted(wanted)],
        )
        return [("id", "in", [rid for (rid,) in self.env.cr.fetchall()])]

    @api.depends("date_confirmed")
    def _compute_sla_elapsed_hours(self) -> None:
        now = fields.Datetime.now()
        for request in self:
            if request.date_confirmed:
                delta = now - request.date_confirmed
                request.sla_elapsed_hours = delta.total_seconds() / 3600
            else:
                request.sla_elapsed_hours = 0.0

    @api.depends("date_confirmed", "category_id.sla_target_hours")
    def _compute_sla_remaining_hours(self) -> None:
        now = fields.Datetime.now()
        for request in self:
            sla_hours = request.category_id.sla_target_hours
            if not sla_hours or not request.date_confirmed:
                request.sla_remaining_hours = 0.0
                continue
            elapsed = (now - request.date_confirmed).total_seconds() / 3600
            request.sla_remaining_hours = sla_hours - elapsed

    @api.depends_context("uid")
    @api.depends(
        "state",
        "approver_ids.state",
        "approver_ids.user_id",
        "approver_ids.delegate_id",
        "approver_ids.delegate_start_date",
        "approver_ids.delegate_end_date",
    )
    def _compute_can_withdraw(self) -> None:
        for request in self:
            request.can_withdraw = (
                request.state in ("pending", "approved")
                and request.user_approver_state == "approved"
            )

    @api.depends_context("uid")
    @api.depends(
        "state",
        "approver_ids.state",
        "approver_ids.user_id",
        "approver_ids.delegate_id",
        "approver_ids.delegate_start_date",
        "approver_ids.delegate_end_date",
    )
    def _compute_is_pending_my_review(self) -> None:
        user = self.env.user
        for request in self:
            request.is_pending_my_review = bool(
                request.state == "pending"
                and request._get_current_pending_approver(user)
            )

    @api.depends_context("uid")
    @api.depends("request_owner_id")
    def _compute_request_access_rights(self) -> None:
        is_manager = is_approval_manager(self.env)
        for request in self:
            request.can_change_request_owner = is_manager
            request.has_access_to_request = (
                request.request_owner_id == self.env.user or is_manager
            )

    @api.depends("approver_ids")
    def _compute_user_ids(self) -> None:
        for request in self:
            request.user_ids = request.approver_ids.user_id

    @api.depends_context("uid")
    @api.depends(
        "approver_ids.state",
        "approver_ids.delegate_id",
        "approver_ids.delegate_start_date",
        "approver_ids.delegate_end_date",
    )
    def _compute_user_approver_state(self) -> None:
        current_user = self.env.user
        for approval in self:
            approval.user_approver_state = approval.approver_ids.filtered(
                lambda approver: approver._get_effective_approver() == current_user,
            )[:1].state

    @api.depends("approver_ids.state")
    def _compute_approval_progress(self) -> None:
        for request in self:
            approvers = request.approver_ids
            if not approvers:
                request.approval_progress = 0.0
                continue

            approved_count = len(approvers.filtered(lambda a: a.state == "approved"))
            total_count = len(approvers)
            request.approval_progress = (
                (approved_count / total_count) * 100.0 if total_count else 0.0
            )

    @api.depends("category_id", "amount", "currency_id", "partner_id", "state")
    def _compute_outcome_prediction(self) -> None:
        stats_cache: dict[tuple[int, int], list] = {}

        def _fetch_bucket(category_id: int, partner_id: int) -> list:
            cache_key = (category_id, partner_id)
            if cache_key in stats_cache:
                return stats_cache[cache_key]
            domain = [
                ("category_id", "=", category_id),
                ("state", "in", list(self._DECISION_STATES)),
            ]
            if partner_id:
                domain.append(("partner_id", "=", partner_id))
            rows = self.search_read(
                domain,
                ["amount", "currency_id", "state"],
                limit=200,
                order="date_confirmed desc",
            )
            stats_cache[cache_key] = rows
            return rows

        for request in self:
            if request.state in self._TERMINAL_STATES:
                request.predicted_outcome = False
                request.prediction_confidence = 0.0
                continue

            rows = _fetch_bucket(
                request.category_id.id,
                request.partner_id.id if request.partner_id else False,
            )
            origin_id = request._origin.id or 0
            tolerance = abs(request.amount) * 0.2
            low, high = request.amount - tolerance, request.amount + tolerance
            similar = [
                r
                for r in rows
                if r["id"] != origin_id
                and (
                    not request.amount
                    or low <= request._prediction_amount_in_own_currency(r) <= high
                )
            ][:20]

            if len(similar) < 3:
                request.predicted_outcome = "uncertain"
                request.prediction_confidence = 0.0
                continue

            approved = sum(1 for r in similar if r["state"] == "approved")
            rate = approved / len(similar)

            if rate >= 0.75:
                request.predicted_outcome = "approve"
                request.prediction_confidence = rate
            elif rate <= 0.25:
                request.predicted_outcome = "refuse"
                request.prediction_confidence = 1.0 - rate
            else:
                request.predicted_outcome = "uncertain"
                request.prediction_confidence = 0.0

    def _prediction_amount_in_own_currency(self, row: dict) -> float:
        self.ensure_one()
        amount = row["amount"]
        row_currency_id = row["currency_id"] and row["currency_id"][0]
        own_currency = self.currency_id
        if (
            not row_currency_id
            or not own_currency
            or row_currency_id == own_currency.id
        ):
            return amount
        rate_datetime = self.date or self.date_confirmed
        rate_date = (
            rate_datetime.date() if rate_datetime else fields.Date.context_today(self)
        )
        return (
            self.env["res.currency"]
            .browse(row_currency_id)
            ._convert(
                amount,
                own_currency,
                self.company_id or self.env.company,
                rate_date,
            )
        )

    @api.depends("state")
    def _compute_is_terminal(self) -> None:
        terminal = self._TERMINAL_STATES
        for request in self:
            request.is_terminal = request.state in terminal

    @api.depends("approver_ids", "approver_ids.state")
    def _compute_pending_approver_ids(self) -> None:
        for request in self:
            pending = request.approver_ids.filtered(lambda a: a.state == "pending")
            request.pending_approver_ids = pending.mapped("user_id")

    @api.depends("approver_ids.state", "approver_ids.required", "approval_minimum")
    def _compute_state(self) -> None:
        for request in self:
            state_lst = request.mapped("approver_ids.state")

            if not state_lst:
                request.state = "new"
                continue

            required_approved = all(
                a.state == "approved" for a in request.approver_ids.filtered("required")
            )

            approval_threshold = request.approval_minimum

            state_counts = Counter(state_lst)

            if state_counts.get("refused", 0) > 0:
                request.state = "refused"
            elif state_counts.get("cancelled", 0) > 0:
                request.state = "cancelled"
            elif state_counts.get("new", 0) > 0:
                request.state = "new"
            elif (
                state_counts.get("approved", 0) >= approval_threshold
                and required_approved
            ):
                request.state = "approved"
            else:
                request.state = "pending"

    def _compute_terminal_date_stamp(self, field_name: str, target_state: str) -> None:
        now = fields.Datetime.now()
        for request in self:
            if request.state != target_state:
                request[field_name] = False
            elif not request[field_name]:
                request[field_name] = now

    @api.depends("state")
    def _compute_date_approval_granted(self) -> None:
        self._compute_terminal_date_stamp("date_approval_granted", "approved")

    @api.depends("state")
    def _compute_date_refused(self) -> None:
        self._compute_terminal_date_stamp("date_refused", "refused")

    @api.depends("state")
    def _compute_date_cancelled(self) -> None:
        self._compute_terminal_date_stamp("date_cancelled", "cancelled")

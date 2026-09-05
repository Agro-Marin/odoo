from typing import Any

from odoo import fields, models


class ApprovalRequestPrediction(models.Model):
    _inherit = "approval.request"

    _PREDICTION_LABELS = {
        "approve": "Likely approved",
        "refuse": "Likely refused",
        "uncertain": "Uncertain",
    }

    def _predict_outcome(self) -> tuple[str | bool, float]:
        self.check_singleton()
        return self._predict_outcomes()[self.id]

    def _predict_outcomes(self) -> dict[int, tuple[str | bool, float]]:
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

        predictions: dict[int, tuple[str | bool, float]] = {}
        for request in self:
            if request.state in self._TERMINAL_STATES:
                predictions[request.id] = (False, 0.0)
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
                predictions[request.id] = ("uncertain", 0.0)
                continue

            approved = sum(1 for r in similar if r["state"] == "approved")
            rate = approved / len(similar)

            if rate >= 0.75:
                predictions[request.id] = ("approve", rate)
            elif rate <= 0.25:
                predictions[request.id] = ("refuse", 1.0 - rate)
            else:
                predictions[request.id] = ("uncertain", 0.0)
        return predictions

    def action_predict_outcome(self) -> dict[str, Any]:
        self.check_singleton()
        outcome, confidence = self._predict_outcome()
        if not outcome:
            message = self.env._("This request is already decided.")
        elif outcome == "uncertain":
            message = self.env._(
                "Not enough comparable decided requests to predict an outcome."
            )
        else:
            message = self.env._(
                "%(label)s (%(confidence)d%% of comparable requests went this way).",
                label=self.env._(self._PREDICTION_LABELS[outcome]),
                confidence=round(confidence * 100),
            )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": self.env._("Outcome prediction"),
                "message": message,
                "type": "info",
                "sticky": False,
            },
        }

    def _prediction_amount_in_own_currency(self, row: dict) -> float:
        self.check_singleton()
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

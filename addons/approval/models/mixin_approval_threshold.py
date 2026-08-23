from odoo import fields, models


class MixinApprovalThreshold(models.AbstractModel):
    _name = "mixin.approval.threshold"
    _description = "Approval Threshold Comparison"

    company_id = fields.Many2one(
        comodel_name="res.company",
        default=lambda self: self.env.company,
        index=True,
        help="Company this record is scoped to. Empty means it applies to "
        "every company, which is how a shared category carries global "
        "tiers and rules (see approval.request._rule_applies_to_company).",
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        default=lambda self: self.env.company.currency_id,
        required=True,
        help="Currency this record's amount thresholds are expressed in. "
        "A request's amount is converted into it before any comparison, "
        "so a global tier or rule on a shared category evaluates "
        "correctly across companies with different currencies.",
    )

    def _convert_request_amount(self, request) -> float:
        self.ensure_one()
        from_currency = request.currency_id
        to_currency = self.currency_id
        if not from_currency or not to_currency or from_currency == to_currency:
            return request.amount
        rate_datetime = request.date or request.date_confirmed
        rate_date = (
            rate_datetime.date() if rate_datetime else fields.Date.context_today(self)
        )
        return from_currency._convert(
            request.amount,
            to_currency,
            request.company_id or self.company_id or self.env.company,
            rate_date,
        )

    @staticmethod
    def _intervals_overlap(bounds_a, bounds_b) -> bool:
        lo_a, lo_a_closed, hi_a, hi_a_closed = bounds_a
        lo_b, lo_b_closed, hi_b, hi_b_closed = bounds_b
        if hi_a < lo_b or (hi_a == lo_b and not (hi_a_closed and lo_b_closed)):
            return False
        return not (hi_b < lo_a or (hi_b == lo_a and not (hi_b_closed and lo_a_closed)))

from __future__ import annotations

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Domain


class HrExpense(models.Model):
    _name = "hr.expense"
    _inherit = ["hr.expense", "mixin.document.extract"]

    _extract_document_type = "receipt"

    extract_can_be_read = fields.Boolean(compute="_compute_extract_can_be_read")

    @api.depends("state", "extract_state")
    def _compute_extract_can_be_read(self) -> None:
        for expense in self:
            expense.extract_can_be_read = expense.state == "draft" and (
                expense.extract_state in ("none", "failed", "partial")
            )

    def _update_from_extraction(self, result) -> None:
        self.ensure_one()
        super()._update_from_extraction(result)

        values = result.flat()
        writes = {}

        if merchant := values.get("merchant_name"):
            if self._extract_name_is_untouched():
                writes["name"] = merchant

        if date := values.get("date"):
            if self._extract_date_is_untouched():
                writes["date"] = date

        writes.update(self._get_extract_amount_values(values, writes.get("date")))

        if writes:
            self.write(writes)

    def _extract_name_is_untouched(self) -> bool:
        self.ensure_one()
        user = self.employee_id.user_id or self.env.user
        untitled = self.with_user(user)._get_untitled_expense_name("").strip()
        return untitled in (self.name or "")

    def _extract_date_is_untouched(self) -> bool:
        self.ensure_one()
        return not self.date or self.date == fields.Date.context_today(
            self, self.create_date
        )

    def _get_extract_amount_values(self, values, date=None) -> dict:
        self.ensure_one()
        total = values.get("total")
        if not total:
            return {}

        writes = {
            "quantity": 1,
            "price_unit": total,
            "total_amount_currency": total,
            "total_amount": total,
        }

        currency = self._get_extract_currency(values.get("currency"))
        if currency and self._extract_currency_is_untouched():
            writes["currency_id"] = currency.id
            if currency != self.company_currency_id:
                writes["total_amount"] = currency._convert(
                    total,
                    self.company_currency_id,
                    company=self.company_id,
                    date=date or self.date,
                )
        return writes

    def _extract_currency_is_untouched(self) -> bool:
        self.ensure_one()
        return not self.currency_id or self.currency_id == self.company_currency_id

    def _get_extract_currency(self, name: str | None):
        if not name:
            return None
        name = name.strip()
        currencies = self.env["res.currency"].with_context(active_test=False)
        for operator in ("=ilike", "ilike"):
            matched = currencies.search(
                Domain.OR(
                    [
                        Domain("currency_unit_label", operator, name),
                        Domain("name", operator, name),
                        Domain("symbol", operator, name),
                    ]
                )
            )
            if len(matched) == 1:
                return matched
        return None

    def action_extract_document(self):
        self.ensure_one()
        if not self.extract_can_be_read:
            raise UserError(_("A receipt is read while the expense is still a draft."))
        result = self._extract_document()
        if result is None:
            return False
        if result.satisfied:
            message = _("The receipt was read in full.")
        else:
            message = _(
                "The receipt was read in part. Still missing: %(fields)s",
                fields=", ".join(result.missing) or _("nothing required"),
            )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {"message": message, "type": "info", "sticky": False},
        }

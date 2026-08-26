from __future__ import annotations

import re

from odoo import models

_REFERENCE_TOKEN = re.compile(r"[^,\s]+")


class AccountMove(models.Model):
    _inherit = "account.move"

    def _update_from_extraction(self, result) -> None:
        self.ensure_one()
        super()._update_from_extraction(result)

        if self.move_type != "in_invoice" or self.invoice_line_ids:
            return

        values = result.flat()
        references = self._get_extract_purchase_order_references(
            values.get("purchase_order")
        )
        if not references:
            return

        self._find_and_set_purchase_orders(
            references,
            self.partner_id.id,
            values.get("total") or 0.0,
            from_ocr=True,
        )

    def _get_extract_purchase_order_references(
        self, reference: str | None
    ) -> list[str]:
        if not reference:
            return []
        return _REFERENCE_TOKEN.findall(reference)

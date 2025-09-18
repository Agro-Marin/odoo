import base64
from typing import Any, Self

from odoo import api, models
from odoo.orm._typing import ValuesType


class ResCompany(models.Model):
    _inherit = "res.company"

    # Fields whose changes require regenerating the company report stylesheet.
    _REPORT_STYLE_FIELDS: frozenset[str] = frozenset(
        {"external_report_layout_id", "font", "primary_color", "secondary_color"}
    )

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        """Regenerate the report style asset when style fields change."""
        companies = super().create(vals_list)
        if any(not self._REPORT_STYLE_FIELDS.isdisjoint(values) for values in vals_list):
            self._update_asset_style()
        return companies

    def write(self, vals: dict[str, Any]) -> bool:
        """Regenerate the report style asset when style fields change."""
        res = super().write(vals)
        if not self._REPORT_STYLE_FIELDS.isdisjoint(vals):
            self._update_asset_style()
        return res

    def _get_asset_style_b64(self) -> bytes:
        """Render the company-report stylesheet for all companies."""
        # One bundle for everyone, so this method
        # necessarily updates the style for every company at once
        company_ids = self.sudo().search([])
        company_styles = self.env["ir.qweb"]._render(
            "web.styles_company_report",
            {
                "company_ids": company_ids,
            },
            raise_if_not_found=False,
        )
        return base64.b64encode(company_styles.encode())

    def _update_asset_style(self) -> None:
        """Update the report-style attachment if the rendered content changed."""
        asset_attachment = self.env.ref(
            "web.asset_styles_company_report", raise_if_not_found=False
        )
        if not asset_attachment:
            return
        asset_attachment = asset_attachment.sudo()
        b64_val = self._get_asset_style_b64()
        if b64_val != asset_attachment.datas:
            asset_attachment.write({"datas": b64_val})

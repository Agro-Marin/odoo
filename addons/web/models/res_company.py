import base64
from typing import Any, Self

from odoo import api, fields, models
from odoo.api import ValuesType


class ResCompany(models.Model):
    _inherit = "res.company"

    # Fields whose changes require regenerating the company report stylesheet.
    _REPORT_STYLE_FIELDS: frozenset[str] = frozenset(
        {
            "external_report_layout_id",
            "font",
            "primary_color",
            "secondary_color",
            "report_theme_id",
        }
    )

    # Report skin (typography, density, shape). Orthogonal to the structural
    # layout (external_report_layout_id) and to the brand colors. Emitted as
    # --rp-* tokens by web.styles_company_report. Empty = built-in defaults.
    report_theme_id = fields.Many2one(
        "report.theme",
        string="Report Theme",
        default=lambda self: self.env.ref(
            "web.report_theme_modern", raise_if_not_found=False
        ),
    )

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        """Regenerate the report style asset when style fields change."""
        companies = super().create(vals_list)
        if any(
            not self._REPORT_STYLE_FIELDS.isdisjoint(values) for values in vals_list
        ):
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
        # One shared asset bundle serves every company, so it must be
        # regenerated from all companies at once, not just the changed ones.
        company_ids = self.sudo().search([])
        company_styles = self.env["ir.qweb"]._render(
            "web.styles_company_report",
            {
                "company_ids": company_ids,
            },
            raise_if_not_found=False,
        )
        return base64.b64encode(company_styles.encode())

    @api.model
    def _set_default_report_theme(self) -> None:
        """Assign the Modern theme to companies that have none.

        Called once from data on web install/upgrade so pre-existing companies
        adopt the token defaults. Idempotent: only fills unset values.
        """
        modern = self.env.ref("web.report_theme_modern", raise_if_not_found=False)
        if not modern:
            return
        self.sudo().search([("report_theme_id", "=", False)]).report_theme_id = modern

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

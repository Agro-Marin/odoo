from typing import Any

from odoo import api, models


class KpiProvider(models.AbstractModel):
    _name = "kpi.provider"
    _description = "KPI Provider"

    @api.model
    def get_kpi_summary(self) -> list[dict[str, Any]]:
        """Return KPI summaries for the databases dashboard; override to add KPIs.

        Each entry is a dict with keys:

        - id: unique identifier
        - type: ``'integer'`` or ``'return_status'``
        - name: translated display name
        - value: number (``type=integer``) or one of ``late``, ``longterm``,
          ``to_do``, ``to_submit``, ``done``
        """
        return []

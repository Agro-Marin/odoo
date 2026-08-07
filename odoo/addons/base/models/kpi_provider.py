from typing import Any

from odoo import api, models


class KpiProvider(models.AbstractModel):
    _name = "kpi.provider"
    _description = "KPI Provider"

    @api.model
    def get_kpi_summary(self) -> list[dict[str, Any]]:
        return []

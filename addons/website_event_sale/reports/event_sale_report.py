from odoo import fields, models
from odoo.tools import frozendict


class EventSaleReport(models.Model):
    _inherit = "event.sale.report"
    _depends = frozendict(
        {
            "event.event": ["is_published"],
        }
    )

    is_published = fields.Boolean(
        string="Published Events",
        readonly=True,
    )

    def _select_clause(self, *select):
        return super()._select_clause(
            "event_event.is_published as is_published", *select
        )

from odoo import api, fields, models
from odoo.fields import Domain


class StockPicking(models.Model):
    _inherit = "stock.picking"

    delay_pass = fields.Datetime(
        compute="_compute_delay_pass",
        search="_search_delay_pass",
        copy=False,
    )

    def _compute_delay_pass(self):
        for picking in self:
            picking.delay_pass = (
                picking._get_source_order_date() or fields.Datetime.now()
            )

    def _get_source_order_date(self):
        self.ensure_one()
        return False

    @api.model
    def _search_delay_pass(self, operator, value):
        paths = self._get_source_order_date_paths()
        if not paths:
            return Domain.FALSE
        return Domain.OR([(path, operator, value)] for path in paths)

    @api.model
    def _get_source_order_date_paths(self):
        return []

    def _effective_transfer_domain(self):
        return Domain([("state", "=", "done"), ("date_done", "!=", False)])

    def _compute_effective_transfer_date(self, field_name, domain):
        effective = self.filtered_domain(domain)
        for picking in self:
            picking[field_name] = picking.date_done if picking in effective else False

    def _search_effective_transfer_date(self, operator, value, domain):
        return Domain.AND([domain, Domain("date_done", operator, value)])

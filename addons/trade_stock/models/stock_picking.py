from odoo import api, fields, models
from odoo.fields import Domain


class StockPicking(models.Model):
    _inherit = "stock.picking"

    delay_pass = fields.Datetime(
        compute="_compute_delay_pass",
        search="_search_delay_pass",
        copy=False,
    )

    @api.depends(lambda self: self._get_source_order_date_paths())
    def _compute_delay_pass(self):
        for picking in self:
            picking.delay_pass = (
                picking._get_source_order_date() or fields.Datetime.now()
            )

    def _get_fields_linking_orders(self):
        return []

    def _get_source_order_date(self):
        self.check_singleton()
        for field in self._get_fields_linking_orders():
            if date_order := self[field].date_order:
                return date_order
        return False

    @api.model
    def _search_delay_pass(self, operator, value):
        paths = self._get_source_order_date_paths()
        if not paths:
            return Domain.FALSE
        return Domain.OR([(path, operator, value)] for path in paths)

    @api.model
    def _get_source_order_date_paths(self):
        return [f"{field}.date_order" for field in self._get_fields_linking_orders()]

    def _get_action_transfer_matching(self, name, res_model, list_view_xmlid):
        self.check_singleton()
        return {
            "type": "ir.actions.act_window",
            "name": name,
            "res_model": res_model,
            "views": [(self.env.ref(list_view_xmlid).id, "list")],
            "domain": [
                ("company_id", "in", self.env.companies.ids),
                (
                    "partner_id",
                    "in",
                    (self.partner_id | self.partner_id.commercial_partner_id).ids,
                ),
                "|",
                ("picking_id", "=", self.id),
                ("picking_id", "=", False),
            ],
        }

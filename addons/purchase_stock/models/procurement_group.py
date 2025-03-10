from odoo import api, fields, models


class ProcurementGroup(models.Model):
    "Inherit ProcurementGroup"

    _inherit = "procurement.group"

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

    purchase_id = fields.Many2one(
        "purchase.order",
        "Purchase Order",
    )
    purchase_line_ids = fields.One2many(
        comodel_name="purchase.order.line",
        inverse_name="procurement_group_id",
        string="Linked Purchase Order Lines",
        copy=False,
    )

    # ------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------

    @api.model
    def run(self, procurements, raise_user_error=True):
        wh_by_comp = dict()
        for procurement in procurements:
            routes = procurement.values.get("route_ids")
            if routes and any(r.action == "buy" for r in routes.rule_ids):
                company = procurement.company_id
                if company not in wh_by_comp:
                    wh_by_comp[company] = self.env["stock.warehouse"].search(
                        [("company_id", "=", company.id)]
                    )
                wh = wh_by_comp[company]
                procurement.values["route_ids"] |= wh.reception_route_id
        return super().run(procurements, raise_user_error=raise_user_error)

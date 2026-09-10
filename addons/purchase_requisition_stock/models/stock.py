from odoo import models


class StockRule(models.Model):
    _inherit = "stock.rule"

    def _prepare_purchase_order_vals(self, company_id, origins, values):
        res = super()._prepare_purchase_order_vals(company_id, origins, values)
        values = values[0]
        res["partner_ref"] = values["supplier"].purchase_requisition_id.name
        res["requisition_id"] = values["supplier"].purchase_requisition_id.id
        if values["supplier"].purchase_requisition_id.currency_id:
            res["currency_id"] = values[
                "supplier"
            ].purchase_requisition_id.currency_id.id
        return res

    def _prepare_po_get_domain(self, company_id, values, partner):
        domain = super()._prepare_po_get_domain(company_id, values, partner)
        if "supplier" in values and values["supplier"].purchase_requisition_id:
            domain += (
                ("requisition_id", "=", values["supplier"].purchase_requisition_id.id),
            )
        return domain

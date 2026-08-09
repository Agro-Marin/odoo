from odoo import models


class IrActionsReport(models.Model):
    _inherit = "ir.actions.report"

    # ------------------------------------------------------------
    # HELPER METHODS
    # ------------------------------------------------------------

    def _get_order_edi_report_map(self):
        # EXTENDS base_order
        return {
            **super()._get_order_edi_report_map(),
            "purchase.report_purchasequotation": "purchase.order",
            "purchase.report_purchaseorder": "purchase.order",
        }

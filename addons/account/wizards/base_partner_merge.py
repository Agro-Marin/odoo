from odoo import models


class BasePartnerMergeAutomaticWizard(models.TransientModel):
    _inherit = "base.partner.merge.automatic.wizard"

    def _get_fields_summable(self):
        return super()._get_fields_summable() + ["customer_rank", "supplier_rank"]

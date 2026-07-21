from odoo import models


class BasePartnerMergeAutomaticWizard(models.TransientModel):
    _inherit = "base.partner.merge.automatic.wizard"

    def _get_summable_fields(self):
        """Add the fields created in this module to the summable fields list."""
        # customer_rank and supplier_rank are summed so the merged partner keeps a better ranking.
        return super()._get_summable_fields() + ["customer_rank", "supplier_rank"]

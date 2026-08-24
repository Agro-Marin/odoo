from odoo import api, models


class Publisher_WarrantyContract(models.AbstractModel):
    _inherit = "publisher_warranty.contract"

    @api.model
    def _get_message(self):
        msg = super()._get_message()
        msg["website"] = True
        return msg

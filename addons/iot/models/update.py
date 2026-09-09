from odoo import api, models


class Publisher_WarrantyContract(models.AbstractModel):
    _inherit = "publisher_warranty.contract"
    _description = "Publisher Warranty Contract For IoT Box"

    @api.model
    def _get_message(self):
        msg = super()._get_message()
        msg["IoTBox"] = self.env["iot.box"].search_count([("version", "=like", "L%")])
        return msg

from odoo import models

from odoo.addons.payment import utils as payment_utils


class ResPartner(models.Model):
    _inherit = "res.partner"

    def _gelato_prepare_address_payload(self):
        first_name, last_name = payment_utils.split_partner_name(self.name)
        address_2 = self.street2 or ""
        if remaining_address := self.street[35:]:
            address_2 = remaining_address + " " + address_2
        return {
            "companyName": (self.commercial_company_name or "")[:60],
            "firstName": (first_name or last_name)[:25],
            "lastName": last_name[:25],
            "addressLine1": self.street[:35],
            "addressLine2": address_2[:35],
            "state": self.state_id.code,
            "city": self.city[:30],
            "postCode": self.zip,
            "country": self.country_id.code,
            "email": self.email,
            "phone": self.phone_ids._primary().number or "",
        }

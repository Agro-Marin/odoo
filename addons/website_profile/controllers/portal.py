from odoo.http import request

from odoo.addons.portal.controllers.portal import CustomerPortal


class CustomerPortalProfile(CustomerPortal):
    def _get_address_errors(self, address_values, partner_sudo, *args, **kwargs):
        if (
            partner_sudo == self.env.user.partner_id
            and "email" in address_values
            and address_values["email"] != partner_sudo.email
        ):
            request.session["validation_email_sent"] = False

        return super()._get_address_errors(
            address_values, partner_sudo, *args, **kwargs
        )

from odoo.http import request

from odoo.addons.sale.controllers import portal as sale_portal


class CustomerPortal(sale_portal.CustomerPortal):
    def _get_payment_values(self, order_sudo, website_id=None, **kwargs):
        if not website_id:
            if order_sudo.website_id:
                website_id = order_sudo.website_id.id
            elif request.website:
                website_id = request.website.id

        return super()._get_payment_values(order_sudo, website_id=website_id, **kwargs)

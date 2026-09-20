from odoo.http import request

from odoo.addons.website_sale.controllers import main


class WebsiteSale(main.WebsiteSale):
    def _prepare_product_values(self, product, category, **kwargs):
        values = super()._prepare_product_values(product, category, **kwargs)
        values["user_email"] = request.env.user.email or request.session.get(
            "stock_notification_email", ""
        )
        return values

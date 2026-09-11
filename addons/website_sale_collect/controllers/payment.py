from odoo import _
from odoo.exceptions import ValidationError

from odoo.addons.website_sale.controllers.payment import PaymentPortal


class OnSitePaymentPortal(PaymentPortal):
    def _check_transaction_for_order(self, transaction, sale_order):
        super()._check_transaction_for_order(transaction, sale_order)

        provider = transaction.provider_id
        if (
            sale_order.carrier_id.delivery_type != "in_store"
            and provider.code == "custom"
            and provider.custom_mode == "on_site"
        ):
            raise ValidationError(
                _(
                    "You can only pay on site when selecting the pick up in store delivery method."
                )
            )

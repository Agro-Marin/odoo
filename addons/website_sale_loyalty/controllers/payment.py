from odoo import _
from odoo.exceptions import ValidationError

from odoo.addons.website_sale.controllers import payment


class PaymentPortal(payment.PaymentPortal):
    def _check_transaction_for_order(self, transaction, sale_order):
        super()._check_transaction_for_order(transaction, sale_order)
        if sale_order.exists():
            initial_amount = sale_order.amount_total
            sale_order._update_programs_and_rewards()
            if sale_order.currency_id.compare_amounts(
                sale_order.amount_total, initial_amount
            ):
                raise ValidationError(
                    _(
                        "Cannot process payment: applied reward was changed or has expired.\n"
                        "Please refresh the page and try again."
                    )
                )

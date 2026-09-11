from odoo.http import request, route

from odoo.addons.account_payment_provider.controllers import payment as account_payment


class PaymentPortal(account_payment.PaymentPortal):
    @route()
    def payment_pay(self, *args, **kwargs):
        return super().payment_pay(*args, website_id=request.website.id, **kwargs)

    @route()
    def payment_method(self, **kwargs):
        return super().payment_method(website_id=request.website.id, **kwargs)

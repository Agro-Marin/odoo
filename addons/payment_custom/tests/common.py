from odoo.fields import Domain

from odoo.addons.payment.tests.common import PaymentCommon


class PaymentCustomCommon(PaymentCommon):
    @classmethod
    def _get_domain_provider(cls, code, custom_mode=None):
        domain = super()._get_domain_provider(code)
        if custom_mode:
            domain = Domain.AND([domain, [("custom_mode", "=", custom_mode)]])
        return domain

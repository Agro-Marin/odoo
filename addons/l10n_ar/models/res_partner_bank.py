import logging

from stdnum.ar.cbu import validate

from odoo import models, api, _

_logger = logging.getLogger(__name__)


class ResPartnerBank(models.Model):
    _inherit = 'res.partner.bank'

    @api.model
    def _get_account_types_supported(self):
        """ Add new account type named cbu used in Argentina """
        res = super()._get_account_types_supported()
        res.append(('cbu', _('CBU')))
        return res

    @api.model
    def _get_acc_type(self, acc_number):
        try:
            validate(acc_number)
        except Exception:
            return super()._get_acc_type(acc_number)
        return 'cbu'

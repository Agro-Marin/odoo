from odoo import api, models


class ResPartner(models.Model):
    _name = 'res.partner'
    _inherit = ['mixin.mail.thread.phone', 'res.partner']

    @api.onchange('phone', 'country_id', 'company_id')
    def _onchange_phone_validation(self):
        if self.phone:
            self.phone = self._phone_format(fname='phone', force_format='INTERNATIONAL') or self.phone

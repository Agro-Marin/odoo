# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import _, models


class Website(models.Model):
    _inherit = "website"

    def get_suggested_controllers(self):
        suggested_controllers = super().get_suggested_controllers()
        suggested_controllers.append((_('References'), self.env['ir.http']._url_for('/customers'), 'website_customer'))
        return suggested_controllers

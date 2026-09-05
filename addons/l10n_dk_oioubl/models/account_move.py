from odoo import models

from odoo.addons.account.tools.import_file_type import CUSTOMIZATION_ID, findtext_equals


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _import_file_type_rules(self):
        # EXTENDS 'account'
        return [
            ('account.edi.xml.oioubl_201', findtext_equals(CUSTOMIZATION_ID, 'OIOUBL-2.01')),
            *super()._import_file_type_rules(),
        ]

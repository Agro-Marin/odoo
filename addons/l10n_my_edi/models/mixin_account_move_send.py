# Part of Odoo. See LICENSE file for full copyright and licensing details.
from odoo import api, models


class MixinAccountMoveSend(models.AbstractModel):
    _inherit = 'mixin.account.move.send'

    # -------------------------------------------------------------------------
    # ATTACHMENTS
    # -------------------------------------------------------------------------

    @api.model
    def _get_invoice_extra_attachments(self, move):
        """ Sharing the XML file may be a requirement, as it doesn't hurt we will do so. """
        # EXTENDS 'account'
        return (
            super()._get_invoice_extra_attachments(move)
            + move._get_active_myinvois_document().myinvois_file_id
        )

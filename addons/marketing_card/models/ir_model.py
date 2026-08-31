from odoo import models, api


class IrModel(models.Model):
    _inherit = 'ir.model'

    @api.ondelete(at_uninstall=False)
    def _unlink_linked_campaigns(self):
        """Remove campaigns on removed models."""
        self.env['card.campaign'].search([
            ('res_model', 'in', self.mapped('model'))
        ]).unlink()

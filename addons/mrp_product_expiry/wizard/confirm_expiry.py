from odoo import api, fields, models
from odoo.exceptions import AccessError


class ExpiryPickingConfirmation(models.TransientModel):
    _inherit = "expiry.picking.confirmation"

    production_ids = fields.Many2many("mrp.production", readonly=True)

    @api.depends("lot_ids", "production_ids")
    def _compute_description(self):
        manufacturing = self.filtered(lambda wizard: wizard.production_ids)
        for wizard in manufacturing:
            if wizard.show_lots:
                wizard.description = self.env._(
                    "You are going to use some expired components."
                    "\nDo you confirm you want to proceed?"
                )
            else:
                wizard.description = self.env._(
                    "You are going to use the component %(product_name)s, %(lot_name)s which is expired."
                    "\nDo you confirm you want to proceed?",
                    product_name=wizard.lot_ids.product_id.display_name,
                    lot_name=wizard.lot_ids.name,
                )
        super(ExpiryPickingConfirmation, self - manufacturing)._compute_description()

    def confirm_produce(self):
        if not self.env.user.has_group("mrp.group_mrp_manager"):
            raise AccessError(
                self.env._(
                    "Only a Manufacturing Manager can confirm a production"
                    " using expired lots."
                )
            )
        body = self.env._(
            "%(user)s confirmed production using expired lot(s): %(lots)s.",
            user=self.env.user.name,
            lots=", ".join(self.lot_ids.mapped("name")),
        )
        self.production_ids._message_log_batch(
            bodies=dict.fromkeys(self.production_ids.ids, body)
        )
        return self.production_ids.with_context(
            **self._validation_context()
        ).button_mark_done()

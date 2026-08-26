from odoo import api, fields, models


class ExpiryPickingConfirmation(models.TransientModel):
    _inherit = "expiry.picking.confirmation"

    production_ids = fields.Many2many("mrp.production", readonly=True)
    workorder_id = fields.Many2one("mrp.workorder", readonly=True)

    @api.depends("lot_ids", "production_ids", "workorder_id")
    def _compute_description(self):
        manufacturing = self.filtered(
            lambda wizard: wizard.production_ids or wizard.workorder_id
        )
        for wizard in manufacturing:
            if wizard.show_lots:
                # For multiple expired lots, they are listed in the wizard view.
                wizard.description = self.env._(
                    "You are going to use some expired components."
                    "\nDo you confirm you want to proceed?"
                )
            else:
                # For one expired lot, its name is written in the wizard message.
                wizard.description = self.env._(
                    "You are going to use the component %(product_name)s, %(lot_name)s which is expired."
                    "\nDo you confirm you want to proceed?",
                    product_name=wizard.lot_ids.product_id.display_name,
                    lot_name=wizard.lot_ids.name,
                )
        super(ExpiryPickingConfirmation, self - manufacturing)._compute_description()

    def confirm_produce(self):
        return self.production_ids.with_context(
            **self._validation_context()
        ).button_mark_done()

    def confirm_workorder(self):
        return self.workorder_id.with_context(
            **self._validation_context()
        ).record_production()

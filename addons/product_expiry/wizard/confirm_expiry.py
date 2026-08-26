from odoo import api, fields, models
from odoo.exceptions import UserError


class ExpiryPickingConfirmation(models.TransientModel):
    _name = "expiry.picking.confirmation"
    _description = "Confirm Expiry"

    lot_ids = fields.Many2many("stock.lot", readonly=True, required=True)
    picking_ids = fields.Many2many("stock.picking", readonly=True)
    description = fields.Char("Description", compute="_compute_description")
    show_lots = fields.Boolean("Show Lots", compute="_compute_show_lots")

    @api.depends("lot_ids")
    def _compute_show_lots(self):
        for wizard in self:
            wizard.show_lots = len(wizard.lot_ids) > 1

    @api.depends("lot_ids")
    def _compute_description(self):
        for wizard in self:
            if wizard.show_lots:
                wizard.description = self.env._(
                    "You are going to deliver some product expired lots."
                    "\nDo you confirm you want to proceed?"
                )
            else:
                wizard.description = self.env._(
                    "You are going to deliver the product %(product_name)s, %(lot_name)s which is expired or should at least be removed from stock."
                    "\nDo you confirm you want to proceed?",
                    product_name=wizard.lot_ids.product_id.display_name,
                    lot_name=wizard.lot_ids.name,
                )

    def _pickings_to_validate(self):
        return self.env["stock.picking"].browse(
            self.env.context.get("button_validate_picking_ids") or []
        )

    def _validation_context(self):
        return {
            key: value
            for key, value in self.env.context.items()
            if not key.startswith("default_")
        } | {"skip_expired": True}

    def process(self):
        pickings = self._pickings_to_validate()
        if not pickings:
            return True
        return pickings.with_context(**self._validation_context()).button_validate()

    def process_no_expired(self):
        pickings = self._pickings_to_validate()
        self.picking_ids.move_line_ids._filtered_expired().unlink()
        remaining = pickings.filtered("move_line_ids")
        if pickings and not remaining:
            raise UserError(
                self.env._(
                    "Every line of this transfer is expired, so there is nothing left to"
                    " deliver. Cancel the transfer, or replace the expired lots before"
                    " validating it."
                )
            )
        return remaining.button_validate()

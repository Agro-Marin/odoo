from odoo import models


class StockReturnPickingLine(models.TransientModel):
    _inherit = "stock.return.picking.line"

    def _prepare_move_default_values(self, new_picking):
        vals = super()._prepare_move_default_values(new_picking)
        # Vendor return: the return move is destined for a supplier location.
        # Link it back to the originating purchase line so the PO's received
        # quantity is decremented and the vendor partner is carried over.
        location_dest = self.env["stock.location"].browse(vals["location_dest_id"])
        if location_dest.usage == "supplier":
            vals["purchase_line_id"], vals["partner_id"] = (
                self.move_id._get_purchase_line_and_partner_from_chain()
            )
        return vals


class StockReturnPicking(models.TransientModel):
    _inherit = "stock.return.picking"

    # ------------------------------------------------------------
    # HELPER METHODS
    # ------------------------------------------------------------

    def _create_return(self):
        picking = super()._create_return()
        if (
            len(picking.move_ids.partner_id) == 1
            and picking.partner_id != picking.move_ids.partner_id
        ):
            picking.partner_id = picking.move_ids.partner_id
        return picking

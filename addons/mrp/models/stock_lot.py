from odoo import api, models
from odoo.exceptions import UserError
from odoo.fields import Domain


class StockLot(models.Model):
    _inherit = "stock.lot"

    def _check_lots_allowed(self, product_ids):
        active_mo_id = self.env.context.get("active_mo_id")
        if active_mo_id:
            active_mo = self.env["mrp.production"].browse(active_mo_id)
            component_product_ids = set(active_mo.move_raw_ids.product_id.ids)
            if (
                not active_mo.picking_type_id.use_create_components_lots
                and set(product_ids) & component_product_ids
            ):
                raise UserError(
                    self.env._(
                        'You are not allowed to create or edit a lot or serial number for the components with the operation type "Manufacturing". To change this, go on the operation type and tick the box "Create New Lots/Serial Numbers for Components".'
                    )
                )
        return super()._check_lots_allowed(product_ids)

    @api.model
    def _get_domain_outgoing_move_lines(self) -> Domain:
        # An unbuild line links the lot it consumes to the component lots it
        # releases, and the production that made the lot links them the other
        # way: following it would credit each lot with the other's deliveries.
        return super()._get_domain_outgoing_move_lines() & Domain(
            "move_id.unbuild_id", "=", False
        )

# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import _, models
from odoo.exceptions import UserError


class StockLot(models.Model):
    _inherit = "stock.lot"

    def _check_create(self):
        active_mo_id = self.env.context.get("active_mo_id")
        if active_mo_id:
            active_mo = self.env["mrp.production"].browse(active_mo_id)
            component_product_ids = set(active_mo.move_raw_ids.product_id.ids)
            # Defaulted: `_check_create` is a hook other modules override and
            # may call, and only `stock.lot.create` guarantees this key. Without
            # the default the intersection below is `None & set` -- a TypeError.
            product_ids = self.env.context.get("lot_product_ids", set())
            if (
                not active_mo.picking_type_id.use_create_components_lots
                and product_ids & component_product_ids
            ):
                raise UserError(
                    _(
                        'You are not allowed to create or edit a lot or serial number for the components with the operation type "Manufacturing". To change this, go on the operation type and tick the box "Create New Lots/Serial Numbers for Components".'
                    )
                )
        return super()._check_create()

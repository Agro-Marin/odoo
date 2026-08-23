# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import models


class StockRule(models.Model):
    _inherit = "stock.rule"

    def _prepare_purchase_order_vals(self, company_id, origins, values):
        if not values[0].get("partner_id") and (
            company_id.subcontracting_location_id.parent_path
            in self.location_dest_id.parent_path
            or self.location_dest_id.is_subcontract()
        ):
            move = values[0].get("move_dest_ids")
            if move and move.raw_material_production_id.subcontractor_id:
                values[0]["partner_id"] = (
                    move.raw_material_production_id.subcontractor_id.id
                )
        return super()._prepare_purchase_order_vals(company_id, origins, values)

    def _prepare_po_get_domain(self, company_id, values, partner):
        """Keep a dropshipped order from merging with one bound elsewhere.

        Only where an order can carry a destination at all: `dest_address_id` is a
        stored compute that `purchase.order._compute_dest_address_id` blanks unless the
        picking type delivers to a customer location, so requiring it to equal the
        procurement's partner on an ordinary receipt matched nothing that could ever
        exist. Every replenishment of a product whose procurement carries a partner then
        opened its own purchase order instead of adding to the draft already waiting --
        the same condition as the compute, so the two cannot drift apart.
        """
        domain = super()._prepare_po_get_domain(company_id, values, partner)
        carries_destination = (
            self.picking_type_id.default_location_dest_id.usage == "customer"
        )
        if values.get("partner_id", False) and carries_destination:
            domain += (("dest_address_id", "=", values.get("partner_id")),)
        return domain

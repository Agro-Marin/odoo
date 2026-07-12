from odoo import _, api, fields, models


class StockWarehouse(models.Model):
    _inherit = "stock.warehouse"

    pos_type_id = fields.Many2one(
        "stock.picking.type", string="Point of Sale Operation Type", copy=False
    )

    def _get_sequence_values(self, name=False, code=False):
        sequence_values = super()._get_sequence_values(name=name, code=code)
        # Honor the name/code params (as the base does) so a warehouse rename or
        # recode propagates here too; `_update_name_and_code` calls this before
        # super().write(), so self.name/self.code are still stale.
        name = name or self.name
        code = code or self.code
        sequence_values.update(
            {
                "pos_type_id": {
                    "name": _("%(name)s Picking POS", name=name),
                    "prefix": code
                    + "/"
                    + (self.pos_type_id.sequence_code or "POS")
                    + "/",
                    "padding": 5,
                    "company_id": self.company_id.id,
                }
            }
        )
        return sequence_values

    def _get_picking_type_update_values(self):
        picking_type_update_values = super()._get_picking_type_update_values()
        picking_type_update_values.update(
            {"pos_type_id": {"default_location_src_id": self.lot_stock_id.id}}
        )
        return picking_type_update_values

    def _get_picking_type_create_values(self, max_sequence):
        picking_type_create_values, max_sequence = (
            super()._get_picking_type_create_values(max_sequence)
        )
        picking_type_create_values.update(
            {
                "pos_type_id": {
                    "name": _("PoS Orders"),
                    "code": "outgoing",
                    "default_location_src_id": self.lot_stock_id.id,
                    "default_location_dest_id": self.env.ref(
                        "stock.stock_location_customers"
                    ).id,
                    "sequence": max_sequence + 1,
                    "sequence_code": "POS",
                    "company_id": self.company_id.id,
                }
            }
        )
        return picking_type_create_values, max_sequence + 2

    @api.model
    def _create_missing_pos_picking_types(self):
        warehouses = self.env["stock.warehouse"].search([("pos_type_id", "=", False)])
        for warehouse in warehouses:
            new_vals = warehouse._create_or_update_sequences_and_picking_types()
            warehouse.write(new_vals)

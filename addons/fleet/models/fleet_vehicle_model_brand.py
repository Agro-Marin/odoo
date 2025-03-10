# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models


class FleetVehicleModelBrand(models.Model):
    _name = "fleet.vehicle.model.brand"
    _description = "Brand of the vehicle"
    _order = "name asc"


    name = fields.Char("Name", required=True)
    active = fields.Boolean(default=True)
    image_128 = fields.Image("Logo", max_width=128, max_height=128)
    model_ids = fields.One2many("fleet.vehicle.model", "brand_id")
    model_count = fields.Integer(compute="_compute_model_count", store=True)


    @api.depends("model_ids")
    def _compute_model_count(self):
        model_data = self.env["fleet.vehicle.model"]._read_group(
            [("brand_id", "in", self.ids)],
            ["brand_id"],
            ["__count"]
        )
        models_brand = {brand.id: count for brand, count in model_data}
        for record in self:
            record.model_count = models_brand.get(record.id, 0)

    def action_brand_model(self):
        self.ensure_one()
        view = {
            "name": "Models",
            "type": "ir.actions.act_window",
            "res_model": "fleet.vehicle.model",
            "view_mode": "list,form",
            "context": {"search_default_brand_id": self.id, "default_brand_id": self.id}
        }
        return view

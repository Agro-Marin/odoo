from odoo import api, fields, models

from odoo.addons.base.models.mixin_catalog import name_uniq_index


class ResCity(models.Model):
    _name = "res.city"
    _description = "City"
    _order = "name"
    _rec_names_search = ["name", "zipcode"]

    name = fields.Char("Name", required=True, translate=True)
    zipcode = fields.Char("Zip")
    country_id = fields.Many2one(
        comodel_name="res.country", string="Country", required=True
    )
    state_id = fields.Many2one(
        comodel_name="res.country.state",
        string="State",
        domain="[('country_id', '=', country_id)]",
    )

    _name_zipcode_country_uniq = name_uniq_index(
        "zipcode",
        "country_id",
        message="A city with this name, zip code and country already exists.",
    )

    @api.depends("zipcode")
    def _compute_display_name(self):
        for city in self:
            name = city.name if not city.zipcode else f"{city.name} ({city.zipcode})"
            city.display_name = name

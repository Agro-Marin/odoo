from odoo import models


class FleetVehicleTag(models.Model):
    _name = 'fleet.vehicle.tag'
    _description = 'Vehicle Tag'
    # `name` (translated, unique), `active`, `color` and `code` all come from
    # the mixin, which already carried the uniqueness rule this model was
    # importing on its own. Flat: vehicle tags do not nest.
    _inherit = ['mixin.tag']

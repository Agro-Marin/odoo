# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models

from odoo.addons.base.models.catalog_mixin import name_uniq_index


class FleetVehicleState(models.Model):
    _name = 'fleet.vehicle.state'
    _order = 'sequence asc'
    _description = 'Vehicle Status'

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer()
    fold = fields.Boolean(string='Folded in Kanban')

    _name_src_uniq = name_uniq_index(
        message='State name already exists',
    )

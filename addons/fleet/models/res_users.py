# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import models, fields


class ResUsers(models.Model):
    _inherit = "res.users"


    vehicle_count = fields.Integer(related="employee_id.vehicle_count")


    @property
    def SELF_READABLE_FIELDS(self):
        return super().SELF_READABLE_FIELDS + ["vehicle_count"]

    def action_open_employee_vehicles(self):
        return self.employee_id.action_open_employee_vehicles()

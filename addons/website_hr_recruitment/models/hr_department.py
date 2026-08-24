from odoo import fields, models


class HrDepartment(models.Model):
    _inherit = "hr.department"

    # Get department name using superuser, because model is not accessible for portal users
    display_name = fields.Char(compute_sudo=True)

from odoo import fields, models


class ResourceResource(models.Model):
    _inherit = "resource.resource"

    appointment_resource_ids = fields.One2many(
        "appointment.resource", "resource_id", export_string_translation=False
    )

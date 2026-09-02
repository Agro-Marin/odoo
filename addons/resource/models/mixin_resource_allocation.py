from odoo import api, fields, models
from odoo.exceptions import ValidationError


class MixinResourceAllocation(models.AbstractModel):
    _name = "mixin.resource.allocation"
    _description = "Resource Allocation Mixin"
    _inherit = ["mixin.resource.scheduling"]

    allocated_percentage = fields.Float(
        "Allocation %",
        default=100.0,
        help="Percentage of the resource's work capacity allocated to this record.",
    )
    allocated_hours = fields.Float(
        "Allocated Hours",
        compute="_compute_allocated_hours",
        store=True,
        readonly=False,
        help="Working hours between scheduling start and end, respecting the resource calendar.",
    )

    @api.constrains("allocated_percentage")
    def _check_allocated_percentage(self):
        for record in self:
            if not 0.0 <= record.allocated_percentage <= 100.0:
                raise ValidationError(
                    self.env._(
                        "%(name)s: allocation %% must be between 0 and 100.",
                        name=record.display_name,
                    )
                )

    def _get_fields_sync_trigger(self):
        return super()._get_fields_sync_trigger() | {"allocated_percentage"}

    @api.depends("reservation_ids.allocated_hours", "reservation_ids.active")
    def _compute_allocated_hours(self):
        for record in self:
            record.allocated_hours = sum(
                record.reservation_ids.mapped("allocated_hours")
            )

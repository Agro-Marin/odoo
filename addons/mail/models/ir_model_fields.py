from typing import Literal

from odoo import fields, models
from odoo.tools import groupby


class IrModelFields(models.Model):
    _inherit = "ir.model.fields"

    tracking = fields.Integer(
        string="Enable Ordered Tracking",
        help="If set every modification done to this field is tracked. Value is used to order tracking values.",
    )

    def _prepare_field_vals(self, field: fields.Field, model_id: int) -> dict:
        vals = super()._prepare_field_vals(field, model_id)
        tracking = getattr(field, "tracking", None)
        if tracking is True:
            tracking = 100
        elif tracking is False:
            tracking = None
        vals["tracking"] = tracking
        return vals

    def _prepare_field_attrs(self, field_data: dict) -> dict:
        attrs = super()._prepare_field_attrs(field_data)
        if field_data.get("tracking"):
            attrs["tracking"] = field_data["tracking"]
        return attrs

    def unlink(self) -> Literal[True]:
        tracked = self.filtered("tracking")
        if tracked:
            tracking_values = self.env["mail.tracking.value"].search(
                [("field_id", "in", tracked.ids)]
            )
            field_to_trackings = groupby(tracking_values, lambda track: track.field_id)
            for field, trackings in field_to_trackings:
                if field.model_id.model not in self.env:
                    continue
                self.env["mail.tracking.value"].concat(*trackings).write(
                    {
                        "field_info": {
                            "desc": field.field_description,
                            "name": field.name,
                            "sequence": self.env[
                                field.model_id.model
                            ]._mail_track_get_field_sequence(field.name),
                            "type": field.ttype,
                        }
                    }
                )
        return super().unlink()

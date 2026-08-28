from odoo import fields, models
from odoo.tools.translate import _


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    order_cycle_interval_number = fields.Integer(
        related="company_id.order_cycle_interval_number",
        readonly=False,
    )
    order_cycle_interval_type = fields.Selection(
        related="company_id.order_cycle_interval_type",
        readonly=False,
    )

    def _clamp_validity_days(self, field_name, label):
        self.ensure_one()
        if self[field_name] >= 0:
            return None
        self[field_name] = self.env["res.company"].default_get([field_name])[field_name]
        return {
            "warning": {
                "title": _("Warning"),
                "message": _(
                    "%(label)s is required and must be greater or equal to 0.",
                    label=label,
                ),
            },
        }

    def _sync_order_lock(self, checkbox_field, lock_field):
        self.ensure_one()
        lock = "lock" if self[checkbox_field] else "edit"
        if self[lock_field] != lock:
            self[lock_field] = lock

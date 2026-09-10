from odoo import fields, models
from odoo.tools.date_utils import get_timedelta, time_unit_selection


class MixinDelay(models.AbstractModel):
    _name = "mixin.delay"
    _description = "Delay Mixin"

    delay_count = fields.Integer("Delay", default=0)
    delay_unit = fields.Selection(
        [
            (unit, label.lower())
            for unit, label in time_unit_selection("day", "week", "month")
        ],
        string="Delay units",
        help="Unit of delay",
        required=True,
        default="day",
    )

    def _get_delay_delta(self):
        self.check_singleton()
        return get_timedelta(self.delay_count, self.delay_unit)

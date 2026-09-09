from odoo import fields, models
from odoo.tools.date_utils import get_timedelta


class MixinDelay(models.AbstractModel):
    _name = "mixin.delay"
    _description = "Delay Mixin"

    delay_count = fields.Integer("Delay", default=0)
    delay_unit = fields.Selection(
        [("days", "days"), ("weeks", "weeks"), ("months", "months")],
        string="Delay units",
        help="Unit of delay",
        required=True,
        default="days",
    )

    def _get_delay_delta(self):
        self.check_singleton()
        return get_timedelta(self.delay_count, self.delay_unit.removesuffix("s"))

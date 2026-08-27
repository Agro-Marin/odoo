from odoo import fields, models
from odoo.tools.date_utils import get_timedelta


class MixinDelay(models.AbstractModel):
    """The "N time units" half of a scheduled offset."""

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
        self.ensure_one()
        # `get_timedelta` is the framework's one spelling of this arithmetic and
        # takes a SINGULAR granularity, which is the vocabulary
        # `mixin.recurrence.rule` and `ir.cron` already use. These two values are
        # stored plural, so normalising them is a data migration rather than a
        # rename; until that is worth doing, the trailing "s" is dropped here so
        # there is still only one implementation of the step.
        return get_timedelta(self.delay_count, self.delay_unit.removesuffix("s"))

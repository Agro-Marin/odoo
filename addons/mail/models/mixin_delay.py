from odoo import fields, models
from odoo.tools.date_utils import get_timedelta


class MixinDelay(models.AbstractModel):
    """The "N time units" half of a scheduled offset.

    ``mail.activity.type`` and ``mail.activity.plan.template`` had grown this
    same pair independently, down to a byte-identical ``delay_unit`` and two
    spellings of one ``relativedelta`` call. The vocabulary is what matters: a
    third consumer should not get to invent a third spelling of "week".

    **``delay_from`` stays with the consumer.** An activity type delays from the
    previous activity's deadline or its completion date; a plan template delays
    before or after the plan date. Those are four different values naming two
    different questions, and a field can only have one selection. The direction
    the delta is applied follows the field, so it stays with the consumer too --
    the same split ``mixin.recurrence.rule`` makes for ``repeat_until``.

    A consumer therefore declares: ``delay_from``, whatever ``string`` it wants
    on ``delay_count``, and how it turns a delta into a date.
    """

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

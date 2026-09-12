from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.date_utils import get_timedelta, time_unit_selection

# "Every N units", and nothing about when it stops.
#
# Split out of `mixin.recurrence.rule` because two consumers need exactly this
# much and would be lying if they took more. A `fleet.vehicle.log.contract`
# accrues its cost every N units and stops when the contract expires; a
# `sale.subscription.plan` bills every N units and stops when the subscription
# is closed. Neither has a `repeat_type` to offer, and inheriting one would have
# put a Selection on the table that is always `forever`, appears in no view and
# is read by nothing -- a column asserting something the model does not mean.
#
# `mixin.recurrence.rule` adds the end policy on top for the consumers that do
# decide it themselves.

REPEAT_UNIT_SELECTION = time_unit_selection("day", "week", "month", "year")


class MixinRecurrenceInterval(models.AbstractModel):
    _name = "mixin.recurrence.interval"
    _description = "Recurrence Interval Mixin"

    repeat_interval = fields.Integer(string="Repeat Every", default=1)
    repeat_unit = fields.Selection(
        REPEAT_UNIT_SELECTION,
        default="week",
        export_string_translation=False,
    )

    @api.constrains("repeat_interval")
    def _check_repeat_interval(self):
        """Python rather than a SQL CHECK: a CHECK fires inside the INSERT and
        hands the user a CheckViolation that has already poisoned the
        transaction, where a ValidationError names the field and leaves the
        transaction usable.
        """
        if self.filtered(lambda record: record.repeat_interval <= 0):
            raise ValidationError(self.env._("The interval should be greater than 0"))

    def _get_recurrence_delta(self):
        self.check_singleton()
        return get_timedelta(self.repeat_interval, self.repeat_unit)

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.date_utils import get_timedelta, time_unit_selection

# The "every N units, until ..." half of a recurrence, in one place.
#
# `project.task.recurrence`, `planning.recurrency` and `maintenance.request`
# had each grown the same rule independently: the same four unit values, the
# same two policy values, the same positive-interval rule written twice -- once
# as a Python constraint and once as a SQL CHECK -- and the same
# step-to-the-next-occurrence helper under two names. This owns that vocabulary
# so a further consumer cannot invent a fourth spelling of "week".
#
# It deliberately does not own `repeat_until`. Three consumers store a Date and
# one (`planning.recurrency`) a Datetime, because its generator needs a precise
# UTC cut-off that a date at midnight would move; a field cannot change type in
# an override, so the column stays with each consumer and only the policy value
# that selects it lives here. It does not own the occurrence generator either:
# copying a task, walking resource availability and enumerating an rrule are
# not variations on a theme.

REPEAT_UNIT_SELECTION = time_unit_selection("day", "week", "month", "year")
REPEAT_TYPE_SELECTION = [
    ("forever", "Forever"),
    ("until", "Until"),
]


class MixinRecurrenceRule(models.AbstractModel):
    _name = "mixin.recurrence.rule"
    _description = "Recurrence Rule Mixin"

    repeat_interval = fields.Integer(string="Repeat Every", default=1)
    repeat_unit = fields.Selection(
        REPEAT_UNIT_SELECTION,
        default="week",
        export_string_translation=False,
    )
    repeat_type = fields.Selection(
        REPEAT_TYPE_SELECTION,
        default="forever",
        string="Until",
        export_string_translation=False,
    )

    @api.constrains("repeat_interval")
    def _check_repeat_interval(self):
        if self.filtered(lambda record: record.repeat_interval <= 0):
            raise ValidationError(self.env._("The interval should be greater than 0"))

    def _get_recurrence_delta(self):
        self.check_singleton()
        return get_timedelta(self.repeat_interval, self.repeat_unit)

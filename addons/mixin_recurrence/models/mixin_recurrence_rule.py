from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.date_utils import get_timedelta, time_unit_selection

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

from calendar import monthrange

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.date_utils import Anchor, next_anchor, previous_anchor

from odoo.addons.base.models.mixin_recurrence_interval import REPEAT_UNIT_SELECTION

WEEKDAY_SELECTION = [
    ("MON", "Monday"),
    ("TUE", "Tuesday"),
    ("WED", "Wednesday"),
    ("THU", "Thursday"),
    ("FRI", "Friday"),
    ("SAT", "Saturday"),
    ("SUN", "Sunday"),
]
WEEKDAY_INDEX = {code: index for index, (code, _label) in enumerate(WEEKDAY_SELECTION)}

DAY_SELECTION = [(str(day), str(day)) for day in range(1, 32)]

MONTH_SELECTION = [
    ("1", "January"),
    ("2", "February"),
    ("3", "March"),
    ("4", "April"),
    ("5", "May"),
    ("6", "June"),
    ("7", "July"),
    ("8", "August"),
    ("9", "September"),
    ("10", "October"),
    ("11", "November"),
    ("12", "December"),
]


# Days and months are Selections of strings rather than integers because the day
# picker narrows its options by the month next to it, and that widget is a
# Selection field; the arithmetic reads them as integers.
class MixinRecurrenceAnchored(models.AbstractModel):
    _name = "mixin.recurrence.anchored"
    _description = "Anchored Recurrence Mixin"

    repeat_unit = fields.Selection(
        REPEAT_UNIT_SELECTION,
        string="Every",
        default="month",
        required=True,
        export_string_translation=False,
    )
    repeat_twice = fields.Boolean(
        string="Twice per Period",
        help="Two anchors in each month or year instead of one",
    )
    repeat_weekday = fields.Selection(
        WEEKDAY_SELECTION, string="Weekday", default="MON"
    )
    repeat_day = fields.Selection(
        DAY_SELECTION,
        compute="_compute_repeat_day",
        store=True,
        readonly=False,
        default="1",
    )
    repeat_month = fields.Selection(MONTH_SELECTION, default="1")
    repeat_second_day = fields.Selection(
        DAY_SELECTION,
        compute="_compute_repeat_second_day",
        store=True,
        readonly=False,
    )
    repeat_second_month = fields.Selection(MONTH_SELECTION, default="7")

    @staticmethod
    def _clamp_day(day, month):
        return str(min(monthrange(2020, int(month))[1], int(day)))

    @api.depends("repeat_month", "repeat_unit")
    def _compute_repeat_day(self):
        for record in self:
            if (
                record.repeat_unit == "year"
                and record.repeat_day
                and record.repeat_month
            ):
                record.repeat_day = self._clamp_day(
                    record.repeat_day, record.repeat_month
                )

    # The second anchor's default depends on the period: the middle of a month,
    # the first of a half-year. It is filled only once a second anchor exists,
    # so a level created as twice a year, whose period is set after the record
    # is, does not keep the month's default.
    @api.depends("repeat_second_month", "repeat_unit", "repeat_twice")
    def _compute_repeat_second_day(self):
        for record in self:
            if not record.repeat_twice:
                continue
            if not record.repeat_second_day:
                record.repeat_second_day = (
                    "15" if record.repeat_unit == "month" else "1"
                )
            elif record.repeat_unit == "year" and record.repeat_second_month:
                record.repeat_second_day = self._clamp_day(
                    record.repeat_second_day, record.repeat_second_month
                )

    @api.constrains(
        "repeat_unit",
        "repeat_twice",
        "repeat_weekday",
        "repeat_day",
        "repeat_month",
        "repeat_second_day",
        "repeat_second_month",
    )
    def _check_repeat_anchors(self):
        for record in self:
            if record.repeat_unit == "week" and not record.repeat_weekday:
                raise ValidationError(self.env._("A weekly schedule needs a weekday."))
            if not record.repeat_twice or record.repeat_unit not in ("month", "year"):
                continue
            first, second = record._get_recurrence_anchors()
            if (first.month or 0, first.day) >= (second.month or 0, second.day):
                raise ValidationError(
                    self.env._("The first day must be lower than the second day.")
                    if record.repeat_unit == "month"
                    else self.env._(
                        "The first date must be earlier in the year than the second date."
                    )
                )

    def _get_recurrence_anchors(self):
        self.check_singleton()
        unit = self.repeat_unit
        if unit == "day":
            return []
        if unit == "week":
            return [Anchor(weekday=WEEKDAY_INDEX[self.repeat_weekday])]
        month = int(self.repeat_month) if unit == "year" else None
        anchors = [Anchor(day=int(self.repeat_day), month=month)]
        if self.repeat_twice:
            second_month = int(self.repeat_second_month) if unit == "year" else None
            anchors.append(Anchor(day=int(self.repeat_second_day), month=second_month))
        return anchors

    def _get_next_anchor(self, after):
        return next_anchor(after, self.repeat_unit, self._get_recurrence_anchors())

    def _get_previous_anchor(self, on):
        return previous_anchor(on, self.repeat_unit, self._get_recurrence_anchors())

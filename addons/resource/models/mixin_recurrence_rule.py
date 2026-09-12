from odoo import fields, models

from odoo.addons.resource.models.mixin_recurrence_interval import (
    REPEAT_UNIT_SELECTION,  # noqa: F401  re-exported: consumers take the whole vocabulary from the rule
)

# The "every N units, until ..." rule, in one place.
#
# `project.task.recurrence`, `planning.recurrency` and `maintenance.request`
# had each grown it independently: the same four unit values, the same two
# policy values, the same positive-interval rule written twice -- once as a
# Python constraint and once as a SQL CHECK -- and the same
# step-to-the-next-occurrence helper under two names. This owns that vocabulary
# so a further consumer cannot invent a fourth spelling of "week".
#
# The interval half lives in `mixin.recurrence.interval`, for the consumers that
# repeat on a cadence but do not decide their own end.
#
# It deliberately does not own `repeat_until`. Three consumers store a Date and
# one (`planning.recurrency`) a Datetime, because its generator needs a precise
# UTC cut-off that a date at midnight would move; a field cannot change type in
# an override, so the column stays with each consumer and only the policy value
# that selects it lives here. It does not own the occurrence generator either:
# copying a task, walking resource availability and enumerating an rrule are
# not variations on a theme.

REPEAT_TYPE_SELECTION = [
    ("forever", "Forever"),
    ("until", "Until"),
]

# The third policy, offered only by the consumers that can honour it. Not in
# `REPEAT_TYPE_SELECTION` because a model that cannot stop after N occurrences
# must not show the option: `project.task.recurrence` and `maintenance.request`
# have no counter to stop on. `planning.recurrency` and `mixin.recurrence.rrule`
# both `selection_add` this one pair rather than each inventing a word for it --
# it used to be `x_times` on one and `count` on the other.
REPEAT_TYPE_COUNT = ("count", "Number of Repetitions")


class MixinRecurrenceRule(models.AbstractModel):
    _name = "mixin.recurrence.rule"
    _description = "Recurrence Rule Mixin"
    _inherit = ["mixin.recurrence.interval"]

    repeat_type = fields.Selection(
        REPEAT_TYPE_SELECTION,
        default="forever",
        string="Until",
        export_string_translation=False,
    )

from odoo import fields, models

# Which occurrences of a recurrence an edit or a deletion applies to.
#
# Three models asked this question and spelled the answer three ways:
# `calendar.event` as self_only/future_events/all_events, `project.task` and
# `planning.slot` as this/subsequent/all with labels naming a task and a shift.
# The values are model-neutral -- an occurrence, the ones after it, all of them
# -- so they are spelled that way here, and a consumer overrides only the labels
# a user reads.
#
# The field is deliberately not stored: it is an instruction attached to one
# write, not a property of the record, and a stored copy would survive the write
# that carried it and silently steer the next one.
RECURRENCE_UPDATE_SELECTION = [
    ("this", "This one"),
    ("subsequent", "This and the following ones"),
    ("all", "All of them"),
]


class MixinRecurrenceOccurrence(models.AbstractModel):
    _name = "mixin.recurrence.occurrence"
    _description = "Recurrence Occurrence Mixin"

    recurrence_update = fields.Selection(
        RECURRENCE_UPDATE_SELECTION,
        default="this",
        store=False,
        copy=False,
    )

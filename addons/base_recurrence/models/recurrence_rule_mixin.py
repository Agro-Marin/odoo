from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.date_utils import get_timedelta


class RecurrenceRuleMixin(models.AbstractModel):
    """The "every N units, until ..." half of a recurrence.

    Two models had grown this same rule independently --
    ``project.task.recurrence`` and ``planning.recurrency`` -- down to the same
    four unit values, the same two policy values, the same ``default=1`` and
    the same "the interval must be positive" rule written twice, once as a
    Python constraint and once as a SQL ``CHECK``. The vocabulary is what
    matters here: a fifth consumer should not get to invent a *fifth* spelling
    of "week".

    What this mixin does **not** own is as deliberate as what it does.

    **``repeat_until`` stays with the consumer, and so does its rule.**
    ``project.task.recurrence`` declares it a ``Date`` and
    ``planning.recurrency`` a ``Datetime``, and that is a real difference
    rather than an accident: a task recurs until the end of a day the user
    picks, a shift until an instant. A field can only have one type, so owning
    it here would force one of them to change its stored data and its widget to
    suit the other. The "an 'until' recurrence must name a date" rule follows
    the field: see :meth:`_check_repeat_interval` for why a shared SQL CHECK
    would have been the wrong shape for it.

    **The occurrence generator stays with the consumer too.** The two are not
    variations on a theme: project copies a task and postpones its dates, while
    planning walks a resource's working intervals and availability to decide
    both whether a slot may be generated and whether it may keep its resource.
    Only :meth:`_get_recurrence_delta` -- the step from one occurrence to the
    next -- is common, and it is here.

    **``repeat_type`` is extensible, not fixed.** ``forever`` and ``until`` are
    the two every consumer needs; planning adds ``x_times`` through
    ``selection_add``. Consumers that add a value must give it an ``ondelete``
    policy, because a selection value is stored data.

    A consumer therefore declares: ``repeat_until``, whatever extra policy
    values it needs, and how it turns a rule into records.
    """

    _name = "recurrence.rule.mixin"
    _description = "Recurrence Rule Mixin"

    # Plain stored fields, which is what makes them safe to own. A computed
    # field could not live here: `@api.depends` unions along the MRO, so a
    # consumer overriding the compute would keep this one's dependency edges as
    # well as its own, permanently and invisibly.
    repeat_interval = fields.Integer(string="Repeat Every", default=1)
    repeat_unit = fields.Selection(
        [
            ("day", "Days"),
            ("week", "Weeks"),
            ("month", "Months"),
            ("year", "Years"),
        ],
        default="week",
        export_string_translation=False,
    )
    repeat_type = fields.Selection(
        [
            ("forever", "Forever"),
            ("until", "Until"),
        ],
        default="forever",
        string="Until",
    )

    @api.constrains("repeat_interval")
    def _check_repeat_interval(self):
        """Reject a non-positive interval.

        Python and not a SQL ``CHECK``, though planning had written it as one.
        A ``CHECK`` is evaluated by the INSERT itself, so it fires *before*
        ``@api.constrains`` ever runs and makes the Python guard unreachable --
        and what the caller then gets is a ``CheckViolation`` that has poisoned
        the transaction, where a ``ValidationError`` names the field and leaves
        the transaction usable. For a value a user types into a form, the
        recoverable error is the right one.

        That asymmetry is also why this mixin owns no rule about
        ``repeat_until``: expressed as a CHECK it would silently replace
        ``project.task.recurrence``'s clean ValidationError, and expressed in
        Python it cannot name a field the mixin does not declare. The rule
        stays with each consumer, in the form that consumer wants.
        """
        if self.filtered(lambda record: record.repeat_interval <= 0):
            raise ValidationError(self.env._("The interval should be greater than 0"))

    def _get_recurrence_delta(self):
        """Return the step from one occurrence to the next.

        ``get_timedelta`` is the framework's own spelling of
        ``relativedelta(**{f"{unit}s": qty})`` and returns exactly that for
        every unit here, so the two consumers' hand-rolled versions were
        already the same function under different names.
        """
        self.ensure_one()
        return get_timedelta(self.repeat_interval, self.repeat_unit)

from odoo.db import schema

# `calendar.recurrence` now takes its rule from `mixin.recurrence.rule`, which
# every other recurrence in this repository already used. The five columns it
# had spelled its own way are renamed, and two of them carry values that change
# with the name: the unit is a `TimeUnit` (`day`, not `daily`) so one vocabulary
# serves the rrule engine and `get_timedelta`, and the end policy is `until`
# rather than `end_date` because that is the word the policy already had on
# `project.task.recurrence`, `planning.recurrency` and `maintenance.request`.
_COLUMN_RENAMES = (
    ("interval", "repeat_interval"),
    ("rrule_type", "repeat_unit"),
    ("end_type", "repeat_type"),
    ("count", "repeat_number"),
    ("until", "repeat_until"),
)

_UNIT_VALUES = {
    "daily": "day",
    "weekly": "week",
    "monthly": "month",
    "yearly": "year",
}


def migrate(cr, version):
    if not version:
        return
    if not schema.table_exists(cr, "calendar_recurrence"):
        return

    for old, new in _COLUMN_RENAMES:
        if not schema.column_exists(cr, "calendar_recurrence", old):
            continue
        if schema.column_exists(cr, "calendar_recurrence", new):
            continue
        # `schema.rename_column`, not a bare ALTER: it carries the NOT NULL
        # constraint's auto-generated name across too, so an upgraded database
        # and a fresh one end up with the same catalog and not merely the same
        # behaviour.
        schema.rename_column(cr, "calendar_recurrence", old, new)

    for old, new in _UNIT_VALUES.items():
        cr.execute(
            "UPDATE calendar_recurrence SET repeat_unit = %s WHERE repeat_unit = %s",
            [new, old],
        )
    cr.execute(
        "UPDATE calendar_recurrence SET repeat_type = 'until' WHERE repeat_type = 'end_date'"
    )

    # The CHECK is rebuilt by the registry from the model, but it names two of
    # the renamed columns and the old unit value, so the stored one has to go
    # first or the rename above leaves a constraint nothing can satisfy.
    cr.execute(
        "ALTER TABLE calendar_recurrence DROP CONSTRAINT IF EXISTS calendar_recurrence_month_day"
    )

    # `ir.filters`, saved searches and any stored domain naming the old columns
    # would silently select nothing; rewriting them is out of scope for a
    # rename, but they are worth reporting rather than leaving to be discovered.
    cr.execute(
        """
        SELECT id, name
          FROM ir_filters
         WHERE model_id = 'calendar.event'
           AND (domain ~ '\\m(rrule_type|end_type)\\M'
                OR context ~ '\\m(rrule_type|end_type)\\M')
        """
    )
    stale = cr.fetchall()
    if stale:
        from logging import getLogger

        getLogger(__name__).warning(
            "calendar: %s saved filter(s) still name the pre-rename recurrence "
            "fields and will match nothing: %s",
            len(stale),
            ", ".join(f"{name} (id={fid})" for fid, name in stale),
        )

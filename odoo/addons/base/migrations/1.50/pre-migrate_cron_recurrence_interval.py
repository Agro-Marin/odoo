import logging

from odoo.tools.module_data import rename_field

_logger = logging.getLogger(__name__)

# `ir.cron` takes its cadence from `mixin.recurrence.interval`: the columns keep
# their data under the shared names, and the unit takes the shared singular
# spelling `get_timedelta` and every other recurrence in the tree already use.
# Renamed in place so the `ir.model.fields` rows keep their ids, which is what
# `mail`'s tracking history on scheduled actions points at.
_UNITS = {
    "minutes": "minute",
    "hours": "hour",
    "days": "day",
    "weeks": "week",
    "months": "month",
}


def migrate(cr, version):
    if not version:
        return

    rename_field(cr, "ir.cron", "interval_number", "repeat_interval")
    rename_field(cr, "ir.cron", "interval_type", "repeat_unit", values=_UNITS)

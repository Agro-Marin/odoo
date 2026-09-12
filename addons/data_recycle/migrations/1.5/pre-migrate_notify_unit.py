from odoo.tools.module_data import rename_field

# The notification cadence speaks the shared time vocabulary: a count and a
# singular unit measured by `get_timedelta`, instead of a plural `relativedelta`
# keyword. Renamed in place so the columns keep their data and the field rows
# their ids. data_cleaning renames its own two consumers.
UNITS = {"days": "day", "weeks": "week", "months": "month"}


def migrate(cr, version):
    if not version:
        return
    for model in ("mixin.data.cleaning.notification", "data_recycle.model"):
        rename_field(cr, model, "notify_frequency", "notify_interval")
        rename_field(cr, model, "notify_frequency_period", "notify_unit", values=UNITS)

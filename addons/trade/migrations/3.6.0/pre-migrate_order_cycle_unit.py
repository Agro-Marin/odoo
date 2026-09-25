from odoo.tools.module_data import rename_field

# The order cycle speaks the shared time vocabulary: a count and a singular unit,
# measured by `get_timedelta` like every other offset in the tree, instead of a
# plural `relativedelta` keyword. Renamed in place so the columns keep their data
# and the field rows their ids.
_UNITS = {"days": "day", "weeks": "week", "months": "month", "years": "year"}


def migrate(cr, version):
    if not version:
        return
    rename_field(cr, "res.company", "order_cycle_interval_number", "order_cycle_count")
    rename_field(
        cr,
        "res.company",
        "order_cycle_interval_type",
        "order_cycle_unit",
        values=_UNITS,
    )

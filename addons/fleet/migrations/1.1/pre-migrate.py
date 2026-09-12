from odoo.db import schema
from odoo.tools import SQL

# The recurring-cost cadence is `mixin.recurrence.interval`'s, not fleet's own.
# Only the column names change: the values were already the shared `TimeUnit`
# vocabulary (`day`/`week`/`month`/`year`), which is what made the pair worth
# folding rather than translating.
_COLUMN_RENAMES = (
    ("cost_frequency_interval", "repeat_interval"),
    ("cost_frequency_unit", "repeat_unit"),
)


def migrate(cr, version):
    if not version:
        return
    if not schema.table_exists(cr, "fleet_vehicle_log_contract"):
        return

    for old, new in _COLUMN_RENAMES:
        if not schema.column_exists(cr, "fleet_vehicle_log_contract", old):
            continue
        if schema.column_exists(cr, "fleet_vehicle_log_contract", new):
            continue
        cr.execute(
            SQL(
                "ALTER TABLE fleet_vehicle_log_contract RENAME COLUMN %s TO %s",
                SQL.identifier(old),
                SQL.identifier(new),
            )
        )

    # `fleet.vehicle.cost.report` is a SQL view over these two columns. Postgres
    # rewrites a view's stored definition on RENAME COLUMN, so it survives -- but
    # the module's `init()` recreates it from `COST_REPORT_QUERY` anyway, and a
    # view holding the old names would make that CREATE OR REPLACE fail on a
    # column list mismatch. Dropping it here leaves `init()` the only author.
    cr.execute("DROP VIEW IF EXISTS fleet_vehicle_cost_report")

    # Tracking rows name the field they recorded; left alone they point at a
    # column that no longer exists and the contract's chatter stops rendering
    # that value's history.
    cr.execute(
        """
        UPDATE ir_model_fields
           SET name = 'repeat_unit'
         WHERE model = 'fleet.vehicle.log.contract'
           AND name = 'cost_frequency_unit'
           AND NOT EXISTS (
               SELECT 1 FROM ir_model_fields existing
                WHERE existing.model = 'fleet.vehicle.log.contract'
                  AND existing.name = 'repeat_unit'
           )
        """
    )

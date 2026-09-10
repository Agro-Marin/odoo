import logging

_logger = logging.getLogger(__name__)

UNITS = (
    ("daily", "day"),
    ("weekly", "week"),
    ("monthly", "month"),
    ("yearly", "year"),
)


def migrate(cr, version):
    if not version:
        return

    _drop_negative_odometer_readings(cr)

    cr.execute(
        """
        SELECT 1
          FROM information_schema.columns
         WHERE table_name = 'fleet_vehicle_log_contract'
           AND column_name = 'cost_frequency'
        """
    )
    if not cr.fetchone():
        return

    cr.execute(
        """
        ALTER TABLE fleet_vehicle_log_contract
          ADD COLUMN IF NOT EXISTS cost_frequency_interval integer,
          ADD COLUMN IF NOT EXISTS cost_frequency_unit varchar
        """
    )
    cr.execute(
        "UPDATE fleet_vehicle_log_contract SET cost_frequency_interval = 1"
        " WHERE cost_frequency_interval IS NULL"
    )
    for old, new in UNITS:
        cr.execute(
            "UPDATE fleet_vehicle_log_contract SET cost_frequency_unit = %s"
            " WHERE cost_frequency = %s",
            (new, old),
        )
    cr.execute(
        "UPDATE fleet_vehicle_log_contract SET cost_frequency_unit = NULL"
        " WHERE cost_frequency = 'no'"
    )
    # ``fleet.vehicle.cost.report`` is a SQL view selecting cost_frequency, and
    # PostgreSQL refuses to drop a column a view depends on. The report rebuilds
    # itself from ``FleetVehicleCostReport.init`` at the end of module loading,
    # so dropping it here costs nothing and is what lets the column go.
    cr.execute("DROP VIEW IF EXISTS fleet_vehicle_cost_report")
    cr.execute("ALTER TABLE fleet_vehicle_log_contract DROP COLUMN cost_frequency")

    cr.execute(
        """
        DELETE FROM ir_model_fields
         WHERE model = 'fleet.vehicle.log.contract'
           AND name = 'cost_frequency'
        """
    )


def _drop_negative_odometer_readings(cr):
    cr.execute(
        "SELECT id, vehicle_id, value FROM fleet_vehicle_odometer WHERE value < 0"
    )
    rows = cr.fetchall()
    if not rows:
        return
    _logger.warning(
        "fleet: dropping %d negative odometer reading(s) so the value >= 0 "
        "constraint can be applied: %s",
        len(rows),
        ", ".join(f"id={r[0]} vehicle={r[1]} value={r[2]}" for r in rows),
    )
    cr.execute("DELETE FROM fleet_vehicle_odometer WHERE value < 0")

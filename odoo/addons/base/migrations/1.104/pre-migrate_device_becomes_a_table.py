import logging

from odoo.db.schema import (
    TableKind,
    column_exists,
    create_column,
    create_model_table,
    drop_view_if_exists,
    get_table_kind,
)
from odoo.tools import SQL

_logger = logging.getLogger(__name__)

_DEVICE_COLUMNS = (
    ("user_id", "int4", None),
    ("session_identifier", "varchar", None),
    ("platform", "varchar", None),
    ("browser", "varchar", None),
    ("device_type", "varchar", None),
    ("ip_address", "varchar", None),
    ("country", "varchar", None),
    ("city", "varchar", None),
    ("first_activity", "timestamp", None),
    ("last_activity", "timestamp", None),
    ("active", "bool", None),
    ("create_uid", "int4", None),
    ("create_date", "timestamp", None),
    ("write_uid", "int4", None),
    ("write_date", "timestamp", None),
)

# The log's per-device columns move to res_device; the ORM drops them from the
# log once their fields are gone, but NOT NULL on session_identifier would
# refuse the log's new inserts until then.
_LOG_COLUMNS_MOVED = (
    "session_identifier",
    "platform",
    "browser",
    "device_type",
    "user_id",
    "revoked",
)


def migrate(cr, version):
    if not version or get_table_kind(cr, "res_device") != TableKind.View:
        return
    drop_view_if_exists(cr, "res_device")
    create_model_table(cr, "res_device", "Devices", _DEVICE_COLUMNS)
    cr.execute(
        """
        INSERT INTO res_device (
            user_id, session_identifier, platform, browser, device_type,
            ip_address, country, city, first_activity, last_activity, active,
            create_uid, create_date, write_uid, write_date
        )
        SELECT DISTINCT ON (user_id, session_identifier, platform, browser)
               user_id, session_identifier, platform, browser, device_type,
               ip_address, country, city,
               min(first_activity) OVER device,
               last_activity,
               NOT bool_and(revoked IS TRUE) OVER device,
               user_id, now() AT TIME ZONE 'UTC', user_id, now() AT TIME ZONE 'UTC'
          FROM res_device_log
         WHERE user_id IS NOT NULL
        WINDOW device AS (PARTITION BY user_id, session_identifier, platform, browser)
         ORDER BY user_id, session_identifier, platform, browser,
                  last_activity DESC NULLS LAST, id DESC
        """
    )
    devices = cr.rowcount
    if not column_exists(cr, "res_device_log", "device_id"):
        create_column(cr, "res_device_log", "device_id", "int4")
    cr.execute(
        """
        UPDATE res_device_log log
           SET device_id = device.id
          FROM res_device device
         WHERE device.user_id = log.user_id
           AND device.session_identifier = log.session_identifier
           AND device.platform IS NOT DISTINCT FROM log.platform
           AND device.browser IS NOT DISTINCT FROM log.browser
        """
    )
    cr.execute("DELETE FROM res_device_log WHERE device_id IS NULL")
    orphans = cr.rowcount
    cr.execute(
        """
        WITH ranked AS (
            SELECT id,
                   row_number() OVER address AS rn,
                   min(first_activity) OVER address AS first_activity
              FROM res_device_log
            WINDOW address AS (
                PARTITION BY device_id, ip_address
                ORDER BY last_activity DESC NULLS LAST, id DESC
                ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
            )
        ),
        kept AS (
            UPDATE res_device_log log
               SET first_activity = ranked.first_activity
              FROM ranked
             WHERE ranked.id = log.id AND ranked.rn = 1
        )
        DELETE FROM res_device_log log
         USING ranked
         WHERE ranked.id = log.id AND ranked.rn > 1
        """
    )
    merged = cr.rowcount
    for column in _LOG_COLUMNS_MOVED:
        if column_exists(cr, "res_device_log", column):
            cr.execute(
                SQL(
                    "ALTER TABLE res_device_log ALTER COLUMN %s DROP NOT NULL",
                    SQL.identifier(column),
                )
            )
    _logger.info(
        "base 1.104: res_device is a table of %s devices; %s log rows merged, "
        "%s without a user dropped",
        devices,
        merged,
        orphans,
    )

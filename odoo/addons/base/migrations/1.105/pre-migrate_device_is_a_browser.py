import logging

from odoo.db.schema import column_exists, create_column, create_model_table
from odoo.tools import SQL

_logger = logging.getLogger(__name__)

_SESSION_COLUMNS = (
    ("device_id", "int4", None),
    ("session_identifier", "varchar", None),
    ("first_activity", "timestamp", None),
    ("last_activity", "timestamp", None),
    ("active", "bool", None),
    ("create_uid", "int4", None),
    ("create_date", "timestamp", None),
    ("write_uid", "int4", None),
    ("write_date", "timestamp", None),
)


def migrate(cr, version):
    if not version or not column_exists(cr, "res_device", "session_identifier"):
        return
    create_model_table(cr, "res_device_session", "Device Session", _SESSION_COLUMNS)
    cr.execute(
        """
        INSERT INTO res_device_session (
            device_id, session_identifier, first_activity, last_activity, active,
            create_uid, create_date, write_uid, write_date
        )
        SELECT id, session_identifier, first_activity, last_activity, active,
               create_uid, create_date, write_uid, write_date
          FROM res_device
        """
    )
    sessions = cr.rowcount
    # Each existing device is one session of one browser; with no browser key
    # known it keeps that identity, hashed as `_device_key_hash` does.
    create_column(cr, "res_device", "key_hash", "varchar")
    cr.execute(
        """
        UPDATE res_device
           SET key_hash = encode(sha256(convert_to(concat_ws(
                   chr(31), 'session', session_identifier,
                   coalesce(platform, ''), coalesce(browser, '')
               ), 'UTF8')), 'hex')
        """
    )
    devices = cr.rowcount
    cr.execute(
        SQL(
            "ALTER TABLE res_device ALTER COLUMN %s DROP NOT NULL",
            SQL.identifier("session_identifier"),
        )
    )
    _logger.info(
        "base 1.105: %s devices keyed by their session, %s sessions recorded",
        devices,
        sessions,
    )

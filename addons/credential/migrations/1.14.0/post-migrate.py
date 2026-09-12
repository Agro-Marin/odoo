import logging

from odoo.db.schema import column_exists

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version or not column_exists(cr, "credential_credential", "is_expired"):
        return

    # Odoo keeps the column of a field that stops being stored; this one held a
    # value frozen at the last write of date_expiration, which is the defect.
    cr.execute("ALTER TABLE credential_credential DROP COLUMN is_expired")
    _logger.info(
        "credential 19.0.1.14.0: dropped credential_credential.is_expired; the "
        "field is read against the current time now instead of the time "
        "date_expiration was last written"
    )

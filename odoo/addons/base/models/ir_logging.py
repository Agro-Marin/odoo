import datetime
import logging

from odoo import api, fields, models
from odoo.libs.constants import GC_UNLINK_LIMIT
from odoo.tools import sql

_logger = logging.getLogger(__name__)

DEFAULT_LOGGING_RETENTION_DAYS = 180
"""Default value (days) for the ``base.logging_retention_days`` parameter."""


class IrLogging(models.Model):
    _name = "ir.logging"
    _description = "Logging"
    _order = "id DESC"
    _allow_sudo_commands = False

    # _log_access fields are defined manually: ir_logging rows are written by raw
    # SQL bypassing the ORM (--log-db may even target a remote DB), so the *_uid
    # one2many fields are meaningless but kept for backward compatibility. Manual
    # definition also avoids the ORM's ALTER TABLE on res_users, whose exclusive
    # lock would deadlock an in-progress install writing its own ir_logging entry.
    create_uid = fields.Integer(string="Created by", readonly=True)
    create_date = fields.Datetime(string="Created on", readonly=True)
    write_uid = fields.Integer(string="Last Updated by", readonly=True)
    write_date = fields.Datetime(string="Last Updated on", readonly=True)

    name = fields.Char(required=True)
    type = fields.Selection(
        [("client", "Client"), ("server", "Server")], required=True, index=True
    )
    dbname = fields.Char(string="Database Name", index=True)
    level = fields.Char(index=True)
    message = fields.Text(required=True)
    path = fields.Char(required=True)
    func = fields.Char(string="Function", required=True)
    # ILOG-M1: stored as Char (not Integer) on purpose -- client-side line refs
    # can be non-numeric (e.g. minified bundle positions). The server writer in
    # logutils passes an int ``lineno`` which PostgreSQL coerces to text.
    line = fields.Char(
        required=True,
        help="Source line. Text rather than integer because client/minified line references may be non-numeric.",
    )

    def init(self) -> None:
        super().init()
        if sql.constraint_definition(
            self.env.cr, "ir_logging", "ir_logging_write_uid_fkey"
        ):
            # Only drop when the constraint actually exists: DROP CONSTRAINT
            # unconditionally takes an ACCESS EXCLUSIVE lock on the table,
            # even when "IF EXISTS" is set and does not match.
            self.env.cr.execute(
                "ALTER TABLE ir_logging DROP CONSTRAINT ir_logging_write_uid_fkey"
            )

    @api.autovacuum
    def _gc_logging(self) -> tuple[int, bool] | None:
        """Drop log entries older than the configured retention period.

        Retention is driven by the ``base.logging_retention_days`` config
        parameter (default ``DEFAULT_LOGGING_RETENTION_DAYS``); a non-positive or
        unparsable value disables collection (with a warning), for deployments
        that archive the table externally.
        """
        param = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("base.logging_retention_days", DEFAULT_LOGGING_RETENTION_DAYS)
        )
        try:
            retention_days = int(param)
        except TypeError, ValueError:
            retention_days = 0
        if retention_days <= 0:
            _logger.warning(
                "Skipping ir.logging garbage collection: "
                "'base.logging_retention_days' is %r (expected a positive "
                "number of days)",
                param,
            )
            return None
        cutoff = self.env.cr.now() - datetime.timedelta(days=retention_days)
        records = self.sudo().search(
            [("create_date", "<", cutoff)], limit=GC_UNLINK_LIMIT
        )
        records.unlink()
        # autovacuum contract: (records removed, whether more may remain)
        return len(records), len(records) == GC_UNLINK_LIMIT

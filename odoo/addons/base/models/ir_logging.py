import datetime
import logging

from odoo import api, fields, models
from odoo.db import schema as sql
from odoo.libs.constants import GC_UNLINK_LIMIT

_logger = logging.getLogger(__name__)

DEFAULT_LOGGING_RETENTION_DAYS = 180
"""Default value (days) for the ``base.logging_retention_days`` parameter."""


class IrLogging(models.Model):
    _name = "ir.logging"
    _description = "Logging"
    _order = "id DESC"
    _allow_sudo_commands = False

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
    line = fields.Char(
        required=True,
        help="Source line. Text rather than integer because client/minified line references may be non-numeric.",
    )

    def init(self) -> None:
        super().init()
        if sql.constraint_definition(
            self.env.cr, "ir_logging", "ir_logging_write_uid_fkey"
        ):
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
        return len(records), len(records) == GC_UNLINK_LIMIT

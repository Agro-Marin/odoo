import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class ResUsersLog(models.Model):
    _name = "res.users.log"
    _order = "id desc"
    _description = "Users Log"
    # Uses the magical fields `create_uid` and `create_date` for recording logins.
    # See `mail.presence` for more recent activity tracking purposes.

    create_uid = fields.Many2one(
        "res.users",
        string="Created by",
        readonly=True,
        index=True,
    )

    @api.autovacuum
    def _gc_user_logs(self) -> None:
        """Garbage-collect login logs, keeping only the latest entry per user.

        For each ``create_uid`` the row with the greatest ``(create_date, id)``
        survives; all older rows in the group are deleted. Rows with a NULL
        ``create_uid`` are never collected (``NULL = NULL`` is never true in the
        correlated EXISTS), so manual/SQL inserts without a creator accumulate.
        """
        self.env.cr.execute("""
            DELETE FROM res_users_log log1 WHERE EXISTS (
                SELECT 1 FROM res_users_log log2
                WHERE log1.create_uid = log2.create_uid
                AND (
                    log1.create_date < log2.create_date
                    OR (log1.create_date = log2.create_date AND log1.id < log2.id)
                )
            )
        """)
        _logger.info("GC'd %d user log entries", self.env.cr.rowcount)

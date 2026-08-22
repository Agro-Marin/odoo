from odoo import api, fields, models
from odoo.tools import SQL


class DocumentsAccessLog(models.Model):

    _name = "documents.access.log"
    _description = "Document Access Log"
    _order = "access_date desc, id desc"
    _log_access = False

    document_id = fields.Many2one(
        "documents.document",
        required=True,
        index=True,
        ondelete="cascade",
        readonly=True,
    )
    partner_id = fields.Many2one(
        "res.partner", required=True, index=True, ondelete="cascade", readonly=True
    )
    action = fields.Selection(
        [("view", "Viewed"), ("download", "Downloaded")],
        required=True,
        readonly=True,
    )
    access_date = fields.Datetime(required=True, readonly=True)

    _document_date_idx = models.Index("(document_id, access_date DESC)")

    @api.model
    def _coalescing_window(self) -> int:
        return int(
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("documents.access_log_window", 3600)
        )

    @api.model
    def _log(self, documents: models.Model, partner: models.Model, action: str) -> None:
        if not documents or not partner:
            return
        window = self._coalescing_window()
        now = fields.Datetime.now()
        self.env.cr.execute(
            SQL(
                """
                INSERT INTO documents_access_log
                            (document_id, partner_id, action, access_date)
                     SELECT document.id, %(partner_id)s, %(action)s, %(now)s
                       FROM UNNEST(%(document_ids)s) AS document(id)
                      WHERE NOT EXISTS (
                            SELECT 1
                              FROM documents_access_log AS recent
                             WHERE recent.document_id = document.id
                               AND recent.partner_id = %(partner_id)s
                               AND recent.action = %(action)s
                               AND recent.access_date > %(cutoff)s
                            )
                """,
                partner_id=partner.id,
                action=action,
                now=now,
                document_ids=documents.ids,
                cutoff=fields.Datetime.subtract(now, seconds=window),
            )
        )

    @api.model
    def _retention_days(self) -> int:
        return int(
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("documents.access_log_retention_days", 365)
        )

    @api.autovacuum
    def _gc_access_log(self) -> tuple:
        retention_days = self._retention_days()
        if retention_days <= 0:
            return 0, False
        limit = 10000
        expired = self.search(
            [
                (
                    "access_date",
                    "<",
                    fields.Datetime.subtract(
                        fields.Datetime.now(), days=retention_days
                    ),
                )
            ],
            limit=limit,
        )
        removed = len(expired)
        expired.unlink()
        return removed, removed == limit

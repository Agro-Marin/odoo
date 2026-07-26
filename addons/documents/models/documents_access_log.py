"""Append-only history of document accesses."""

from odoo import api, fields, models
from odoo.tools import SQL


class DocumentsAccessLog(models.Model):
    """Append-only record of who reached a document, and when.

    ``documents.access.last_access_date`` holds a single, overwritten timestamp
    per (document, partner): it answers "when did this person last touch it",
    which is what the "Recent" folder and the last-accessed grouping need, and
    it is all the module recorded. It cannot answer the question an audit
    actually asks -- *who downloaded this document in March* -- because every
    earlier visit was overwritten by the next one.

    This model keeps the history that timestamp discards. It is written to, and
    garbage-collected, but never updated: a row is a statement that something
    happened, and rewriting it would defeat the point.
    """

    _name = "documents.access.log"
    _description = "Document Access Log"
    _order = "access_date desc, id desc"
    _log_access = False  # `access_date` and `partner_id` are the record

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

    # "Everything that happened to this document, most recent first" is the
    # query this exists to serve.
    _document_date_idx = models.Index("(document_id, access_date DESC)")

    @api.model
    def _coalescing_window(self) -> int:
        """Seconds within which a repeated access is not logged again.

        Access logging sits on paths a browsing user hits repeatedly -- opening
        a shared folder re-registers every document in it -- so an unconditional
        insert would trade a real audit trail for a write amplifier. One row per
        (document, partner, action) per window keeps the history answerable
        while bounding the volume. Set the parameter to ``0`` to record every
        single access.
        """
        return int(
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("documents.access_log_window", 3600)
        )

    @api.model
    def _log(self, documents: models.Model, partner: models.Model, action: str) -> None:
        """Record ``partner`` performing ``action`` on ``documents``.

        Deliberately one statement, and deliberately not the ORM: this runs on
        read paths, including anonymous ones, where the cost has to stay flat
        and a failure must not take the request with it. The ``NOT EXISTS``
        applies the coalescing window in the same round trip that inserts, so
        two concurrent hits cannot both decide they are the first (and if they
        somehow do, the result is a duplicate row -- harmless in an append-only
        log -- rather than an error).
        """
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
        self.invalidate_model()

    @api.model
    def _retention_days(self) -> int:
        return int(
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("documents.access_log_retention_days", 365)
        )

    @api.autovacuum
    def _gc_access_log(self) -> tuple:
        """Drop entries past the retention window.

        Returns the autovacuum ``(removed, maybe more)`` contract so a long
        backlog is drained across runs instead of in one unbounded delete.
        """
        retention_days = self._retention_days()
        if retention_days <= 0:  # 0 disables expiry: keep everything
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

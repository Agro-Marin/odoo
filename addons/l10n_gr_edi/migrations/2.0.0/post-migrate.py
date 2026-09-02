import logging

from odoo.db.schema import column_exists, table_exists

_logger = logging.getLogger(__name__)

_STATE_TO_TRANSMISSION = {
    "invoice_sent": ("mydata.invoice", "accepted"),
    "invoice_error": ("mydata.invoice", "rejected"),
    "bill_sent": ("mydata.classification", "accepted"),
    "bill_error": ("mydata.classification", "rejected"),
    "bill_fetched": ("mydata.classification", "draft"),
}


def migrate(cr, version):
    """Every myDATA document becomes a transmission.

    `l10n_gr_edi.document` held two documents about one move in one Selection --
    an invoice and an expense classification -- which is the axis
    exchange.transmission carries as `document_kind`. `bill_fetched` is not a
    verdict at all: it is a classification we have not sent yet, so it becomes a
    draft carrying the mark the authority gave us to quote.
    """
    from odoo import SUPERUSER_ID, api

    if not table_exists(cr, "l10n_gr_edi_document"):
        _logger.info("No myDATA document table; nothing to rebuild")
        return

    env = api.Environment(cr, SUPERUSER_ID, {})
    cr.execute(
        """
        SELECT d.id, d.move_id, d.state, d.datetime, d.message, d.attachment_id,
               d.mydata_mark, d.mydata_cls_mark, d.mydata_url, m.company_id
          FROM l10n_gr_edi_document d
          JOIN account_move m ON m.id = d.move_id
         WHERE d.move_id IS NOT NULL
         ORDER BY d.id
        """,
    )
    rows = cr.dictfetchall()
    if not rows:
        return

    channels = {}
    values = []
    for row in rows:
        mapped = _STATE_TO_TRANSMISSION.get(row["state"])
        if not mapped:
            continue
        kind, state = mapped
        company_id = row["company_id"]
        if company_id not in channels:
            # The company's own channel if it has one, else the shared record
            # the module ships -- the same rule `_get_exchange_channel_of` uses.
            channels[company_id] = env["exchange.channel"].search(
                [("protocol", "=", "mydata"), ("company_id", "=", company_id)],
                limit=1,
            ) or env["exchange.channel"].search(
                [("protocol", "=", "mydata"), ("company_id", "=", False)],
                limit=1,
            )
        channel = channels[company_id]
        if not channel:
            _logger.warning(
                "Company %s has no myDATA channel; %s documents not rebuilt",
                company_id,
                row["state"],
            )
            continue
        values.append(
            {
                "subject_id": f"account.move,{row['move_id']}",
                "channel_id": channel.id,
                "company_id": company_id,
                "intent": "issue",
                "document_kind": kind,
                "state": state,
                "reference": row["mydata_cls_mark"] or row["mydata_mark"] or False,
                "message": row["message"] or "",
                "attachment_id": row["attachment_id"],
                "date_created": row["datetime"],
                "l10n_gr_edi_mark": row["mydata_mark"] or False,
                "l10n_gr_edi_url": row["mydata_url"] or False,
            },
        )

    if values:
        env["exchange.transmission"].create(values)
        _logger.info("Rebuilt %d transmission(s) from myDATA history", len(values))

    if column_exists(cr, "account_move", "l10n_gr_edi_state"):
        env["account.move"].search(
            [("l10n_gr_edi_state", "!=", False)]
        )._compute_from_l10n_gr_edi_document_ids()

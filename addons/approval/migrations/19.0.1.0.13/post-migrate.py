import logging

from odoo import api

_logger = logging.getLogger(__name__)

_PLACEHOLDER_NAMES = ["New", "Nuevo", "Nueva", "Nouveau"]


def migrate(cr, version):
    env = api.Environment(cr, api.SUPERUSER_ID, {})

    manual_seq = env["approval.request"]._get_sequence_manual()
    cr.execute(
        "UPDATE approval_approver SET source_synced = TRUE WHERE sequence != %s",
        [manual_seq],
    )
    _logger.info(
        "approval 19.0.1.0.13: marked %d approver row(s) as source-synced.",
        cr.rowcount,
    )

    cr.execute(
        "SELECT id FROM approval_request WHERE name = ANY(%s)",
        [_PLACEHOLDER_NAMES],
    )
    ids = [row[0] for row in cr.fetchall()]
    if not ids:
        return

    drafts = renumbered = 0
    for request in env["approval.request"].browse(ids):
        if not request.date_confirmed:
            request.name = False
            drafts += 1
            continue
        sequence = request.category_id.sequence_id
        if not sequence:
            _logger.warning(
                "Request %s has a placeholder name but its category %r "
                "has no sequence; leaving as-is.",
                request.id,
                request.category_id.display_name,
            )
            continue
        request.name = sequence.next_by_id()
        renumbered += 1

    _logger.info(
        "approval 19.0.1.0.13: cleared %d draft placeholder name(s), "
        "assigned sequence numbers to %d confirmed request(s).",
        drafts,
        renumbered,
    )

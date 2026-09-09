import logging

from odoo.tools.module_data import repair_orphaned_cron_actions

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Re-point the server-action companion 1.8 left behind.

    1.8 moved `ir_cron_find_and_set_documents_expired` from `document_compliance`
    to `document` and renamed it, but a cron loaded from XML owns a second xmlid
    -- `<cron xmlid>_ir_actions_server` -- and that one stayed where it was. It
    did nothing until `document_compliance` next appeared in `updated_modules`;
    then `ir.model.data._process_end()` read it as stale and tried to delete the
    server action out from under a live cron, which
    `ir_cron_ir_actions_server_id_fkey` refuses.

    Because the sweep runs after every module has upgraded and committed, the
    resulting `-u all` fails at the last step with the database already migrated.
    1.8 now moves the pair together, which covers anything still below it; this
    covers the databases that already ran it.

    Deliberately not scoped to that one xmlid: the helper repairs any companion
    whose cron has moved on without it, and a database that has none is a no-op.
    """
    if not version:
        return
    repaired = repair_orphaned_cron_actions(cr)
    _logger.info(
        "1.13: re-pointed %d cron server-action companion(s) left by a rename",
        repaired,
    )

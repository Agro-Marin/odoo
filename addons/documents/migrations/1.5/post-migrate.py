"""Repair the seeded Inbox alias's parent pairing on existing databases."""

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Backfill ``alias_parent_model_id`` on the seeded Inbox alias.

    The alias is declared in a ``noupdate="1"`` data file, so adding the field
    to the XML only fixes fresh installs -- upgrading leaves existing databases
    with ``alias_parent_thread_id`` set and ``alias_parent_model_id`` empty.

    Mail gates every consumer of the parent on *both* fields being set, so in
    that half-configured state ``open_parent_document()`` returns False (the
    "Open Parent Document" buttons stay hidden by their ``invisible=`` guards)
    and ``mail.thread._alias_get_error`` resolves to an empty recordset instead
    of the Inbox folder.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    alias = env.ref(
        "documents.document_inbox_folder_mail_alias", raise_if_not_found=False
    )
    # Only repair the half-configured pairing this migration is about: leave a
    # deliberately-set parent alone, and do not invent one where the thread is
    # missing too (nothing identifies which record it should point at).
    if not alias or alias.alias_parent_model_id or not alias.alias_parent_thread_id:
        return
    alias.alias_parent_model_id = env["ir.model"]._get_id("documents.document")

r"""Pre-migration: follow the ``action_open_*`` -> ``action_view_*`` renames.

Five names that inheriting views locate by name were renamed without a
migration. None of them survives anywhere in the tree, so every stored arch
still naming one is a view that cannot be combined any more::

    action_open_versions            -> action_view_versions
    action_open_goals               -> action_view_goals
    action_open_work_entries        -> action_view_work_entries
    action_open_manufacturing_order -> action_view_manufacturing_order
    module_account_payment          -> module_account_payment_provider

The last follows the ``account_payment`` -> ``account_payment_provider`` module
rename that ``account``'s own 1.9-1.13 chain performs; the settings checkbox is
a field, located the same way and broken the same way.

Why the whole set runs from ``base``: the views live across ``hr``,
``hr_payroll``, ``hr_appraisal``, ``planning``, ``mrp_workorder_expiry``,
``account_payment_provider`` and six more, and a view breaks as soon as *its
parent* reloads -- not when its own module does. Only ``base`` is guaranteed to
have run before all of them. Each is rewritten from its own data file later in
the same upgrade; this only has to carry them through the window.

Whole-word (``\y``) rewriting over ``ir_ui_view`` is safe precisely because the
old names are extinct in the tree -- and ``\y`` does not fire inside
``module_account_payment_provider``, since an underscore is a word character.

Rehearsal note: this is deliberately one script covering five modules' lapses.
Upstream each rename belongs in the renaming module's own pre-migration.
"""

import logging
import typing

if typing.TYPE_CHECKING:
    from odoo.db.cursor import Cursor

_logger = logging.getLogger(__name__)

RENAMES = {
    "action_open_versions": "action_view_versions",
    "action_open_goals": "action_view_goals",
    "action_open_work_entries": "action_view_work_entries",
    "action_open_manufacturing_order": "action_view_manufacturing_order",
    "module_account_payment": "module_account_payment_provider",
}


def migrate(cr: "Cursor", version: str | None) -> None:
    if not version:
        return

    for old, new in RENAMES.items():
        cr.execute(
            r"""
            UPDATE ir_ui_view
               SET arch_db = regexp_replace(
                       arch_db::text, '\y' || %s || '\y', %s, 'g'
                   )::jsonb
             WHERE arch_db::text ~ ('\y' || %s || '\y')
            """,
            (old, new, old),
        )
        if cr.rowcount:
            _logger.info("Renamed %s -> %s in %d view(s)", old, new, cr.rowcount)

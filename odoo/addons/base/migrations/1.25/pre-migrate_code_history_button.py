r"""Pre-migration: follow the ``action_open_code_history`` button rename.

``ir.actions.server``'s code-history button is now
``action_view_code_history`` (``ir_actions_server.py``, and the button itself in
``views/ir_actions_views.xml``). ``base.ir_cron_view_form`` xpaths that button by
name to drop it from the cron form, and the new file already names the new one.

The stored arch is what breaks the upgrade. ``base`` loads
``views/ir_actions_views.xml`` before ``views/ir_cron_views.xml``, and writing
the parent revalidates every view inheriting it -- so the *old* cron arch, still
xpathing ``action_open_code_history``, is checked against the *new* parent that
no longer has that button, and validation fails with "Element ... cannot be
located in parent view" before the file that would have fixed the child is ever
read. ``_process_end`` cleans up superseded views only after data loading, which
is likewise too late.

Rewriting the name in place is enough: both stored views are overwritten by
their own data files later in this same upgrade, so this only has to survive
the window between the two.

Idempotent: the ``LIKE`` guard stops matching once the rename has been applied.
"""

import logging
import typing

if typing.TYPE_CHECKING:
    from odoo.db.cursor import Cursor

_logger = logging.getLogger(__name__)

OLD = "action_open_code_history"
NEW = "action_view_code_history"


def migrate(cr: "Cursor", version: str | None) -> None:
    if not version:
        return

    cr.execute(
        """
        UPDATE ir_ui_view
           SET arch_db = replace(arch_db::text, %s, %s)::jsonb
         WHERE arch_db::text LIKE %s
        """,
        (OLD, NEW, f"%{OLD}%"),
    )
    if cr.rowcount:
        _logger.info(
            "Renamed %s -> %s in %d stored view arch(s)", OLD, NEW, cr.rowcount
        )

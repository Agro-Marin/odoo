# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.tools import SQL

from . import models

#: The modules this one was merged from. Both were ``auto_install`` on
#: ``portal`` plus an always-installed parent, so on any database that had
#: ``portal`` they are installed and their records exist.
_ABSORBED_MODULES = ["auth_totp_portal", "auth_passkey_portal"]

#: ``(old module, old name) -> new name`` for the external IDs this merge also
#: renames. Everything else keeps its name and only changes owner, so the
#: records are re-owned rather than recreated.
_RENAMED_XMLIDS = {
    ("auth_totp_portal", "access_auth_totp_portal_wizard"): (
        "access_auth_totp_wizard_portal"
    ),
}


def pre_init_hook(env):
    """Take ownership of ``auth_totp_portal`` and ``auth_passkey_portal``'s data.

    Both modules were merged into this one, so their directories are gone from
    the addons path. A module missing from disk is skipped by the module graph
    but keeps its ``ir_module_module`` row and its ``ir_model_data`` rows, and
    the records behind them — the two ``portal.portal_my_security`` extensions
    among them. Installing ``auth_portal`` on such a database would then add a
    *second* copy of each section to the portal security page.

    Reassigning the external IDs before this module's data is loaded makes the
    load an update of the existing records instead. Runs on install only, and
    is a no-op on a database that never had the old modules.
    """
    cr = env.cr

    cr.execute(
        SQL(
            "SELECT name FROM ir_module_module WHERE name = ANY(%s)",
            _ABSORBED_MODULES,
        )
    )
    if not cr.fetchall():
        return

    # A view's ``key`` carries the owning module too, and QWeb resolves by key.
    cr.execute(
        SQL(
            """
            UPDATE ir_ui_view
               SET key = 'auth_portal.' || substring(key FROM position('.' IN key) + 1)
             WHERE split_part(key, '.', 1) = ANY(%s)
            """,
            _ABSORBED_MODULES,
        )
    )

    for (module, name), new_name in _RENAMED_XMLIDS.items():
        cr.execute(
            SQL(
                """
                UPDATE ir_model_data SET module = 'auth_portal', name = %s
                 WHERE module = %s AND name = %s
                   AND NOT EXISTS (
                       SELECT 1 FROM ir_model_data
                        WHERE module = 'auth_portal' AND name = %s
                   )
                """,
                new_name,
                module,
                name,
                new_name,
            )
        )

    # Whatever is left keeps its name. An ID this module no longer declares is
    # then a stale row owned by an updated module, which ``_process_end``
    # collects at the end of the load along with the record behind it.
    cr.execute(
        SQL(
            """
            UPDATE ir_model_data SET module = 'auth_portal'
             WHERE module = ANY(%s)
               AND NOT EXISTS (
                   SELECT 1 FROM ir_model_data existing
                    WHERE existing.module = 'auth_portal'
                      AND existing.name = ir_model_data.name
               )
            """,
            _ABSORBED_MODULES,
        )
    )

    # Drop the now-empty module records. Their own ``base.module_*`` external
    # IDs go first, or they would dangle at a res_id that no longer exists.
    cr.execute(
        SQL(
            """
            DELETE FROM ir_model_data
             WHERE model = 'ir.module.module'
               AND module = 'base'
               AND name = ANY(%s)
            """,
            [f"module_{name}" for name in _ABSORBED_MODULES],
        )
    )
    cr.execute(
        SQL(
            """
            DELETE FROM ir_module_module_dependency
             WHERE module_id IN (
                 SELECT id FROM ir_module_module WHERE name = ANY(%s)
             )
            """,
            _ABSORBED_MODULES,
        )
    )
    cr.execute(
        SQL("DELETE FROM ir_module_module WHERE name = ANY(%s)", _ABSORBED_MODULES)
    )

    env.invalidate_all()

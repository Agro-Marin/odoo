"""Rewrite stored ``ir.module.module`` view archs after the
``installed_version`` -> ``manifest_version`` field rename.

Runs as a base ``pre`` migration so the archs are corrected before base reloads
``module_tree`` and re-validates its child views (e.g. delivery's), which would
otherwise fail on the now-removed field name. Idempotent via the LIKE guard.
"""


def migrate(cr, version):
    cr.execute(
        """
        UPDATE ir_ui_view
           SET arch_db = replace(
                   arch_db::text, 'installed_version', 'manifest_version'
               )::jsonb
         WHERE model = 'ir.module.module'
           AND arch_db::text LIKE '%installed_version%'
        """
    )

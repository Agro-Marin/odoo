OLD_MODULE = "web_enterprise"


def _module_state(cr, name):
    cr.execute("SELECT state FROM ir_module_module WHERE name = %s", [name])
    row = cr.fetchone()
    return row[0] if row else None


def migrate(cr, version):
    # web_enterprise is folded into web: the two inherited views it declared
    # are now web's own templates, the homemenu_config column and its data
    # stay, every other record it declared moves to web's namespace, and the
    # module row is closed so nothing tries to load a directory that is no
    # longer on disk.
    if _module_state(cr, OLD_MODULE) is None:
        return
    cr.execute(
        """
        DELETE FROM ir_ui_view
         WHERE id IN (
            SELECT res_id FROM ir_model_data
             WHERE module = %s AND model = 'ir.ui.view'
         )
        """,
        [OLD_MODULE],
    )
    cr.execute(
        "DELETE FROM ir_model_data WHERE module = %s AND model = 'ir.ui.view'",
        [OLD_MODULE],
    )
    cr.execute(
        """
        UPDATE ir_model_data d
           SET module = 'web'
         WHERE d.module = %s
           AND NOT EXISTS (
               SELECT 1 FROM ir_model_data p
                WHERE p.module = 'web' AND p.name = d.name
           )
        """,
        [OLD_MODULE],
    )
    cr.execute("DELETE FROM ir_model_data WHERE module = %s", [OLD_MODULE])
    cr.execute(
        """
        DELETE FROM ir_module_module_dependency
         WHERE module_id IN (SELECT id FROM ir_module_module WHERE name = %s)
        """,
        [OLD_MODULE],
    )
    cr.execute(
        "UPDATE ir_module_module SET state = 'uninstalled' WHERE name = %s",
        [OLD_MODULE],
    )

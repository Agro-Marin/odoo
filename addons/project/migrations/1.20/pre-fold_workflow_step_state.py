OLD_MODULE = "project_workflow_step_state"


def _module_state(cr, name):
    cr.execute("SELECT state FROM ir_module_module WHERE name = %s", [name])
    row = cr.fetchone()
    return row[0] if row else None


def migrate(cr, version):
    # project_workflow_step_state (an OCA-derived agromarin module) is folded
    # into project: the task_state column and its data stay, the records it
    # declared move to project's namespace, its two inherited views go, and
    # the module row is closed so nothing tries to load a directory that is
    # no longer on disk.
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
           SET module = 'project'
         WHERE d.module = %s
           AND NOT EXISTS (
               SELECT 1 FROM ir_model_data p
                WHERE p.module = 'project' AND p.name = d.name
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

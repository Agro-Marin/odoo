from odoo.tools.module_data import rename_in_stored_expressions

MODEL = "project.task"
OLD_METHOD = "action_fsm_view_overlapping_tasks"
NEW_METHOD = "action_view_overlapping_tasks"


def migrate(cr, version):
    if not version:
        return

    rename_in_stored_expressions(cr, OLD_METHOD, NEW_METHOD, model=MODEL)

from odoo.tools.module_data import rename_in_stored_expressions

MODEL = "project.task"
OLD_FIELD = "stage_id"
NEW_FIELD = "step_id"


def migrate(cr, version):
    if not version:
        return

    rename_in_stored_expressions(cr, OLD_FIELD, NEW_FIELD, model=MODEL)

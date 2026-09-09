"""Post-migration: ``action_fsm_view_overlapping_tasks`` lost its ``fsm_`` prefix.

The method came from ``project_enterprise``, where nothing about it was field
service; it is the button on the planning-overlap warning, which is now a
community field. ``industry_fsm`` still overrides it under the new name.
"""

from odoo.tools.module_data import rename_in_stored_expressions

MODEL = "project.task"
OLD_METHOD = "action_fsm_view_overlapping_tasks"
NEW_METHOD = "action_view_overlapping_tasks"


def migrate(cr, version):
    """Repoint stored expressions at the renamed method.

    :param cr: database cursor
    :param version: installed module version; falsy on a fresh install
    """
    if not version:
        return

    rename_in_stored_expressions(cr, OLD_METHOD, NEW_METHOD, model=MODEL)

"""Post-migration: stored expressions still naming ``project.task.stage_id``.

``stage_id`` became ``step_id``. The 1.19 rename pass carried the renames into
``ir_act_server.code`` and into view buttons, but not into ``mail.template``,
which no upgrade reloads because every template is ``noupdate``.
``project.rating_project_request_email_template`` therefore kept five
references to ``object.stage_id`` and raises ``AttributeError`` for every task
it is rendered against.

That template is archived here and no workflow step enables rating, so nothing
sends it today -- but archived is not deleted, and a step that turns rating on
would reach it through ``step_id.rating_template_id``, which does not filter on
``active``.

Scoped to ``project.task``: ``stage_id`` is still a live field on other models,
so an unscoped rewrite would corrupt ``crm.lead`` and ``hr.applicant``.
"""

from odoo.tools.module_data import rename_in_stored_expressions

MODEL = "project.task"
OLD_FIELD = "stage_id"
NEW_FIELD = "step_id"


def migrate(cr, version):
    """Repoint stored expressions at the renamed field.

    :param cr: database cursor
    :param version: installed module version; falsy on a fresh install
    """
    if not version:
        return

    rename_in_stored_expressions(cr, OLD_FIELD, NEW_FIELD, model=MODEL)

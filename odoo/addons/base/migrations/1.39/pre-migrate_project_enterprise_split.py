"""Pre-migration: ``project_enterprise`` split into three modules.

Everything that did not need ``web_gantt`` or ``web_map`` moved into community
``project``; the gantt views stayed behind in a module renamed to
``project_gantt``; the map views moved to a new ``project_map``.

This runs in ``base`` rather than in ``project`` because the module row itself
has to be renamed before the graph is assembled: a ``project`` migration runs
after the loader has already decided that ``project_enterprise`` is installed
and missing from disk.
"""

import logging

_logger = logging.getLogger(__name__)

OLD_MODULE = "project_enterprise"
NEW_MODULE = "project_gantt"

# xml ids that stayed in the renamed module but under a new name. Everything else
# is left alone on purpose: the records that moved to `project` or to the new
# `project_map` keep their rows under project_gantt until that module loads, and
# `_process_end` then reaps both the row and the record it points at, because
# project_gantt's data files no longer declare them. Deleting them here instead
# would leave the ir.ui.view rows behind with no xml id to reap them by, and the
# map views would sit in the registry naming a `user_names` field that only
# project_map declares.
RENAMED = {
    "view_task_kanban_inherited_project_enterprise": "project_task_view_kanban_in_gantt",
}

# Records the renamed module no longer declares, deleted here rather than left
# to `_process_end`. Reaping runs at the END of the load, and two things happen
# before it that a stale row breaks:
#
#   * an `ir.ui.view` that INHERITS a view whose arch this split changed is
#     re-validated while the base module loads, and its xpath no longer matches
#     -- `project_enterprise.portal_my_task` replaced
#     `//div[@t-if='task.date_end']`, which is now the base template's own
#     markup, so the upgrade died on `industry_fsm.portal_my_task` naming a
#     view neither module owns any more;
#   * an `ir.actions.act_window.view` the new owner re-creates against the same
#     action and view_mode collides on
#     `ir_act_window_view_unique_mode_per_action`.
#
# Both are deleted records and all. Nothing inherits an act_window.view, and the
# views below are themselves inheriting views that the new owner re-creates or
# that the base view now carries inline. The `ir.exports.line` moved to project
# under the same name and would collide on nothing, but it is listed for the
# same reason: project re-creates it.
SUPERSEDED = {
    "ir.actions.act_window.view": (
        "ir_act_window_view",
        (
            # to project_map
            "project_all_task_map_action_view",
            "project_task_map_action_view",
            "project_task_from_milestone_action_map_view",
            # to project, which now owns the kanban/list/calendar ordering pins
            # on project.action_view_task_from_milestone
            "action_view_task_from_milestone_kanban_view",
            "action_view_task_from_milestone_tree_view",
            "action_view_task_from_milestone_calendar_view",
        ),
    ),
    "ir.ui.view": (
        "ir_ui_view",
        (
            # The ONLY view that has to go early. It replaced
            # `//div[@t-if='task.date_end']` in project's portal template, and
            # that markup is now the base template's own, so the stale arch
            # matches nothing -- and the error names `industry_fsm.portal_my_task`,
            # an innocent third module. Every other view this module lost still
            # has a resolving xpath, so the reaper handles them at end of load.
            #
            # Deleting more than this is not an option, and the attempt is worth
            # recording: `ir_ui_view_inherit_id_fkey` is RESTRICT, not CASCADE, so
            # deleting a view another view inherits raises RestrictViolation.
            # `portal_my_task` is safe because nothing inherits it.
            "portal_my_task",
        ),
    ),
    "ir.exports.line": (
        "ir_exports_line",
        ("project_task_export_template_line_planned_date_begin",),
    ),
}


def migrate(cr, version):
    cr.execute("SELECT id FROM ir_module_module WHERE name = %s", (OLD_MODULE,))
    if not cr.fetchone():
        return

    # `= ANY(%s)` with a list, never `IN %s`: psycopg 3 binds server-side, so the
    # placeholder reaches PostgreSQL as $2 and `IN $2` is a syntax error.
    for model, (table, names) in SUPERSEDED.items():
        # `{table}` is interpolated from SUPERSEDED above and never from input.
        cr.execute(
            f"""
            DELETE FROM {table}
                  WHERE id IN (SELECT res_id
                                 FROM ir_model_data
                                WHERE module = %s AND model = %s
                                  AND name = ANY(%s))
            """,
            (OLD_MODULE, model, list(names)),
        )
        deleted = cr.rowcount
        cr.execute(
            "DELETE FROM ir_model_data "
            "WHERE module = %s AND model = %s AND name = ANY(%s)",
            (OLD_MODULE, model, list(names)),
        )
        _logger.info("dropped %s superseded %s record(s)", deleted, model)

    for old_name, new_name in RENAMED.items():
        cr.execute(
            "UPDATE ir_model_data SET name = %s WHERE module = %s AND name = %s",
            (new_name, OLD_MODULE, old_name),
        )

    cr.execute(
        "UPDATE ir_model_data SET module = %s WHERE module = %s",
        (NEW_MODULE, OLD_MODULE),
    )
    cr.execute(
        "UPDATE ir_module_module_dependency SET name = %s WHERE name = %s",
        (NEW_MODULE, OLD_MODULE),
    )
    cr.execute(
        "UPDATE ir_module_module SET name = %s WHERE name = %s",
        (NEW_MODULE, OLD_MODULE),
    )
    _logger.info("renamed module %s to %s", OLD_MODULE, NEW_MODULE)

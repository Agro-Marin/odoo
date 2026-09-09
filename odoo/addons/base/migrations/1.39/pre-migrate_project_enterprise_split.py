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

# The one exception to leaving the reaping alone. These three
# ``ir.actions.act_window.view`` rows move to ``project_map``, which re-creates
# them against the same action and the same view_mode, and
# ``ir_act_window_view_unique_mode_per_action`` rejects the second one. Reaping
# runs at the END of the load, after project_map has already tried to insert, so
# the old rows have to go first. Deleted outright, records and all: nothing
# inherits an act_window.view.
MAP_ACTION_VIEWS = (
    "project_all_task_map_action_view",
    "project_task_map_action_view",
    "project_task_from_milestone_action_map_view",
)


def migrate(cr, version):
    cr.execute("SELECT id FROM ir_module_module WHERE name = %s", (OLD_MODULE,))
    if not cr.fetchone():
        return

    # `= ANY(%s)` with a list, never `IN %s`: psycopg 3 binds server-side, so the
    # placeholder reaches PostgreSQL as $2 and `IN $2` is a syntax error.
    cr.execute(
        """
        DELETE FROM ir_act_window_view
              WHERE id IN (SELECT res_id
                             FROM ir_model_data
                            WHERE module = %s
                              AND model = 'ir.actions.act_window.view'
                              AND name = ANY(%s))
        """,
        (OLD_MODULE, list(MAP_ACTION_VIEWS)),
    )
    cr.execute(
        """
        DELETE FROM ir_model_data
              WHERE module = %s
                AND model = 'ir.actions.act_window.view'
                AND name = ANY(%s)
        """,
        (OLD_MODULE, list(MAP_ACTION_VIEWS)),
    )
    _logger.info("dropped %s map act_window.view row(s)", cr.rowcount)

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

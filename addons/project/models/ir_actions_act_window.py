from odoo import api, models

# The task actions that offer every view type project ships. A bridge adding a
# view type -- gantt, map -- inserts it into all of them at install rather than
# restating each action's whole view_mode, which two bridges cannot do without
# the later one erasing the earlier one's view.
TASK_ACTIONS_WITH_ALL_VIEWS = (
    "project.action_view_task",
    "project.action_view_my_task",
    "project.action_view_all_task",
    "project.action_view_task_from_milestone",
    "project.project_task_action_sub_task",
    "project.project_task_action_from_partner",
    "project.act_project_project_2_project_task_all",
    "project.project_milestone_action_view_tasks",
)

PROJECT_ACTIONS_WITH_ALL_VIEWS = (
    "project.open_view_project_all_group_stage",
    "project.open_view_project_all_config_group_stage",
)


class IrActionsAct_Window(models.Model):
    _inherit = "ir.actions.act_window"

    @api.model
    def _insert_view_mode(self, xmlids, view_type, before=None):
        """Insert ``view_type`` into each action's ``view_mode``, before ``before``.

        Never at position 0, so the action's default view is whatever it already
        was. ``view_mode`` order decides the switcher's button order and nothing
        else, and the orders this replaces were hand-written per action and
        inconsistent with each other, so no single rule reproduces all of them.
        """
        for xmlid in xmlids:
            action = self.env.ref(xmlid, raise_if_not_found=False)
            if not action:
                continue
            modes = action.view_mode.split(",")
            if view_type in modes:
                continue
            index = modes.index(before) if before in modes else len(modes)
            modes.insert(max(index, 1), view_type)
            action.view_mode = ",".join(modes)

    @api.model
    def _insert_task_view_mode(self, view_type, before=None):
        """Add ``view_type`` to every task action that offers the full view set."""
        self._insert_view_mode(TASK_ACTIONS_WITH_ALL_VIEWS, view_type, before)

    @api.model
    def _insert_project_view_mode(self, view_type, before=None):
        """Add ``view_type`` to every project action that offers the full view set."""
        self._insert_view_mode(PROJECT_ACTIONS_WITH_ALL_VIEWS, view_type, before)

    @api.model
    def _remove_view_mode(self, xmlids, view_type):
        for xmlid in xmlids:
            action = self.env.ref(xmlid, raise_if_not_found=False)
            if not action:
                continue
            modes = [mode for mode in action.view_mode.split(",") if mode != view_type]
            if modes and len(modes) != len(action.view_mode.split(",")):
                action.view_mode = ",".join(modes)

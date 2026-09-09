from lxml import html

from odoo import api, models
from odoo.tools import html2plaintext

_BLOCK_TAGS = (
    "p",
    "div",
    "li",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "blockquote",
    "pre",
    "td",
)

_TITLE_MAX_LENGTH = 100


class ProjectTask(models.Model):
    _name = "project.task"
    _inherit = "project.task"

    @api.model
    def _todo_name_from_description(self, description):
        if not description:
            return ""
        try:
            fragment = html.fragment_fromstring(description, create_parent="div")
        except ValueError, SyntaxError:
            fragment = None
        if fragment is not None:
            for element in fragment.iterdescendants(*_BLOCK_TAGS):
                line = " ".join(element.itertext()).strip()
                if line:
                    break
            else:
                line = " ".join(fragment.itertext()).strip()
        else:
            line = html2plaintext(description).strip().partition("\n")[0]
        line = " ".join(line.split())
        if len(line) > _TITLE_MAX_LENGTH:
            line = line[: _TITLE_MAX_LENGTH - 3] + "..."
        return line

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name") or vals.get("project_id") or vals.get("parent_id"):
                continue
            vals["name"] = self._todo_name_from_description(
                vals.get("description")
            ) or self.env._("Untitled to-do")
        return super().create(vals_list)

    def action_convert_to_task(self):
        self.check_singleton()
        self.company_id = self.project_id.company_id
        return {
            "view_mode": "form",
            "res_model": "project.task",
            "res_id": self.id,
            "type": "ir.actions.act_window",
        }

    @api.model
    def get_todo_views_id(self):
        return [
            (
                self.env["ir.model.data"]._xmlid_to_res_id(
                    "project_todo.project_task_view_todo_kanban"
                ),
                "kanban",
            ),
            (
                self.env["ir.model.data"]._xmlid_to_res_id(
                    "project_todo.project_task_view_todo_tree"
                ),
                "list",
            ),
            (
                self.env["ir.model.data"]._xmlid_to_res_id(
                    "project_todo.project_task_view_todo_form"
                ),
                "form",
            ),
            (
                self.env["ir.model.data"]._xmlid_to_res_id(
                    "project_todo.project_task_view_todo_calendar"
                ),
                "calendar",
            ),
            (
                self.env["ir.model.data"]._xmlid_to_res_id(
                    "project_todo.project_task_view_todo_activity"
                ),
                "activity",
            ),
        ]

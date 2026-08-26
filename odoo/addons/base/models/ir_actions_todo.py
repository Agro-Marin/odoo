from typing import Any, Self

from odoo import api, fields, models
from odoo.api import ValuesType


class IrActionsTodo(models.Model):
    _name = "ir.actions.todo"
    _description = "Configuration Wizards"
    _rec_name = "action_id"
    _order = "sequence, id"
    _allow_sudo_commands = False

    name = fields.Char()
    sequence = fields.Integer(default=10)
    action_id = fields.Many2one(
        "ir.actions.actions",
        string="Action",
        required=True,
        index=True,
        ondelete="cascade",
    )
    state = fields.Selection(
        [("open", "To Do"), ("done", "Done")],
        string="Status",
        default="open",
        required=True,
    )

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        todos = super().create(vals_list)
        todos._close_other_open_todos()
        return todos

    def write(self, vals: dict[str, Any]) -> bool:
        res = super().write(vals)
        if vals.get("state") == "open":
            self._close_other_open_todos()
        return res

    def unlink(self) -> bool:
        todos = self
        try:
            todo_open_menu = self.env.ref("base.open_menu")
            default_action = self.env.ref("base.action_client_base_menu")
        except ValueError:
            pass
        else:
            if todo_open_menu in todos:
                todo_open_menu.action_id = default_action.id
                todos -= todo_open_menu
        return super(IrActionsTodo, todos).unlink()

    def _close_other_open_todos(self) -> None:
        keep = self.filtered(lambda todo: todo.state == "open").sorted()[:1]
        if not keep:
            return
        self.search([("state", "=", "open"), ("id", "not in", keep.ids)]).write(
            {"state": "done"}
        )

    def action_launch(self) -> dict[str, Any]:
        self.ensure_one()
        self.state = "done"

        action = self.action_id._get_action_concrete()
        result = action._get_action_dict()
        if action._name != "ir.actions.act_window":
            return result

        ctx = action._eval_action_context(result.get("context"))
        if ctx.get("res_id"):
            result["res_id"] = ctx.pop("res_id")
        ctx["disable_log"] = True
        result["context"] = ctx
        return result

    def action_open(self) -> bool:
        return self.write({"state": "open"})

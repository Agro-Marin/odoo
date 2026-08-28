from typing import Any

from werkzeug.exceptions import BadRequest

from odoo import _
from odoo.exceptions import AccessError, MissingError, UserError
from odoo.http import Controller, request, route

from .utils import clean_action


class MissingActionError(UserError):
    pass


class Action(Controller):
    @route("/web/action/load", type="jsonrpc", auth="user", readonly=True)
    def load(
        self, action_id: int | str, context: dict[str, Any] | None = None
    ) -> dict[str, Any] | bool:
        if context:
            request.update_context(**context)
        Actions = request.env["ir.actions.actions"]
        try:
            action_id = int(action_id)
        except ValueError:
            try:
                if "." in action_id:
                    action = request.env.ref(action_id)
                    if not action._name.startswith("ir.actions."):
                        msg = "Not an action"
                        raise ValueError(msg)
                else:
                    action = Actions._get_action_by_path(action_id)
                    if not action:
                        msg = "Action not found"
                        raise ValueError(msg)
                action_id = action.id
            except (ValueError, KeyError, AttributeError, MissingError) as exc:
                raise MissingActionError(
                    _("The action '%s' does not exist.", action_id)
                ) from exc

        base_action = Actions.browse([action_id]).sudo().read(["type"])
        if not base_action:
            raise MissingActionError(_("The action '%s' does not exist", action_id))
        action_type = base_action[0]["type"]
        if action_type == "ir.actions.report":
            request.update_context(bin_size=True)
        action = request.env[action_type].sudo().browse([action_id])
        return clean_action(action._get_action_dict(), env=request.env)

    @route("/web/action/run", type="jsonrpc", auth="user")
    def run(
        self, action_id: int, context: dict[str, Any] | None = None
    ) -> dict[str, Any] | bool:
        if context:
            request.update_context(**context)
        action = request.env["ir.actions.server"].browse([action_id])
        result = action.run()
        return clean_action(result, env=action.env) if result else False

    @route(
        "/web/action/load_breadcrumbs",
        type="jsonrpc",
        auth="user",
        readonly=True,
    )
    def load_breadcrumbs(self, actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        results = []
        for idx, action in enumerate(actions):
            try:
                results.append(self._get_breadcrumb(action, idx, actions))
            except (MissingActionError, MissingError, AccessError) as exc:
                results.append({"error": str(exc)})
        return results

    def _get_breadcrumb(
        self, action: dict[str, Any], idx: int, actions: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """One breadcrumb entry, from an action id/path or from a bare model."""
        record_id = action.get("resId")
        if action.get("action"):
            return self._get_action_breadcrumb(action, record_id, idx, actions)
        if action.get("model"):
            Model = request.env[action.get("model")]
            if not record_id:
                msg = "Actions with a model should also have a resId"
                raise BadRequest(msg)
            if record_id == "new":
                return {"display_name": _("New")}
            return {"display_name": Model.browse(record_id).display_name}
        msg = "Actions should have either an action (id or path) or a model"
        raise BadRequest(msg)

    def _get_action_breadcrumb(
        self,
        action: dict[str, Any],
        record_id: Any,
        idx: int,
        actions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """The breadcrumb of an action reference, or the error that stopped it."""
        act = self.load(action.get("action"))
        if not act:
            return {"error": f"Action {action.get('action')!r} could not be loaded"}

        if act["type"] == "ir.actions.server":
            if not act["path"]:
                return {"error": "A server action must have a path to be restored"}
            act = request.env["ir.actions.server"].browse(act["id"]).run()
            if not isinstance(act, dict):
                return {"error": "Server action did not return a restorable action"}

        if not act.get("display_name"):
            act["display_name"] = act["name"]

        if (
            act["type"] == "ir.actions.client"
            and idx + 1 < len(actions)
            and action.get("action") == actions[idx + 1].get("action")
        ):
            return {"error": "Client actions don't have multi-record views"}

        if record_id:
            if record_id == "new":
                return {"display_name": _("New")}
            if act["res_model"]:
                return {
                    "display_name": request.env[act["res_model"]]
                    .browse(record_id)
                    .display_name
                }
            return {"display_name": act["display_name"]}

        if act.get("res_model") and act["type"] != "ir.actions.client":
            request.env[act["res_model"]].check_access("read")
            name = (
                act["display_name"]
                if any(
                    view[1] != "form" and view[1] != "search" for view in act["views"]
                )
                else None
            )
        else:
            name = act["display_name"]
        return {"display_name": name}

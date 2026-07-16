import threading
from typing import Any

from werkzeug.exceptions import NotFound

from odoo import http
from odoo.http import request
from odoo.service.model import call_kw

from .utils import clean_action


class DataSet(http.Controller):
    def _call_kw_readonly(self, rule: Any, args: Any) -> bool:
        # Guard the whole param extraction uniformly: a malformed body missing
        # ``params``/``model``/``method`` (or naming an unknown model) should
        # resolve to a clean 404 during routing, not a raw 500 from a
        # half-guarded KeyError.
        try:
            params = request.get_json_data()["params"]
            model_class = request.registry[params["model"]]
            method_name = params["method"]
        except KeyError as e:
            raise NotFound from e
        for cls in model_class.mro():
            method = getattr(cls, method_name, None)
            if method is not None and hasattr(method, "_readonly"):
                return method._readonly
        return False

    @http.route(
        ["/web/dataset/call_kw", "/web/dataset/call_kw/<path:path>"],
        type="jsonrpc",
        auth="user",
        readonly=_call_kw_readonly,
    )
    def call_kw(
        self,
        model: str,
        method: str,
        args: list[Any],
        kwargs: dict[str, Any],
        path: str | None = None,
    ) -> Any:
        if path != f"{model}.{method}":
            threading.current_thread().rpc_model_method = f"{model}.{method}"
        return call_kw(request.env[model], method, args, kwargs)

    @http.route(
        ["/web/dataset/call_button", "/web/dataset/call_button/<path:path>"],
        type="jsonrpc",
        auth="user",
        readonly=_call_kw_readonly,
    )
    def call_button(
        self,
        model: str,
        method: str,
        args: list[Any],
        kwargs: dict[str, Any],
        path: str | None = None,
    ) -> dict[str, Any] | bool:
        if path != f"{model}.{method}":
            threading.current_thread().rpc_model_method = f"{model}.{method}"
        action = call_kw(request.env[model], method, args, kwargs)
        # type="" is a sentinel meaning "no action"; a dict with no "type" key
        # gets one defaulted to act_window_close by clean_action()
        if isinstance(action, dict) and action.get("type") != "":
            return clean_action(action, env=request.env)
        return False

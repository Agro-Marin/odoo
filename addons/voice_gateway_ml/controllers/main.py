from odoo import http
from odoo.exceptions import AccessError
from odoo.http import request

from odoo.addons.voice_gateway_ml.tools.intent import (
    can_interpret,
    interpret_sentence,
)


class VoiceGatewayMlController(http.Controller):
    @http.route("/voice_gateway_ml/available", type="jsonrpc", auth="user")
    def available(self) -> dict:
        return {
            "available": request.env.user._is_internal() and can_interpret(request.env)
        }

    @http.route("/voice_gateway_ml/interpret", type="jsonrpc", auth="user")
    def interpret(self, text: str, choices: list) -> dict:
        if not request.env.user._is_internal():
            raise AccessError(request.env._("Voice commands are for internal users."))
        return {"actions": interpret_sentence(request.env, text, choices)}

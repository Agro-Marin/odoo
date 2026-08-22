from odoo import api, models
from odoo.tools import config

from ..websocket import WebsocketConnectionHandler


def _websocket_session_info() -> dict:
    info = {"websocket_worker_version": WebsocketConnectionHandler._VERSION}
    if config["workers"] and not config["proxy_mode"]:
        info["websocket_gevent_port"] = config["gevent_port"]
    return info


class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    @api.model
    def get_frontend_session_info(self):
        session_info = super().get_frontend_session_info()
        session_info.update(_websocket_session_info())
        return session_info

    def session_info(self):
        session_info = super().session_info()
        session_info.update(_websocket_session_info())
        return session_info

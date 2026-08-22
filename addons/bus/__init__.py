from odoo.http import register_session_rotation_excluded_paths

register_session_rotation_excluded_paths(
    "/websocket/on_closed",
    "/websocket/peek_notifications",
    "/websocket/update_bus_presence",
)

from . import models
from . import tools
from . import controllers
from . import websocket

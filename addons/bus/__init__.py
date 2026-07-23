from odoo.http import register_session_rotation_excluded_paths

# Websocket bootstrap/polling endpoints are hit many times per minute; rotating
# the session there wastes a disk write per call and reopens the soft-rotate
# race. Declared here — where the endpoints live — instead of hardcoding bus
# URLs inside odoo.http (see odoo/http/constants.py).
register_session_rotation_excluded_paths(
    "/websocket/on_closed",
    "/websocket/peek_notifications",
    "/websocket/update_bus_presence",
)

from . import models
from . import tools
from . import controllers
from . import websocket

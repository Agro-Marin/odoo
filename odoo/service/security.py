import logging
import time
from typing import TYPE_CHECKING

from odoo.tools.misc import consteq

if TYPE_CHECKING:
    from odoo.api import Environment

_logger = logging.getLogger(__name__)


def compute_session_token(session: object, env: Environment) -> str | bool:
    self = env["res.users"].browse(session.uid)
    return self._compute_session_token(session.sid)


def check_session(
    session: object,
    env: Environment,
    request: object | None = None,
) -> bool:
    session._delete_old_sessions()
    if "deletion_time" in session and session["deletion_time"] <= time.time():
        return False
    expected = compute_session_token(session, env)
    actual = session.session_token
    if not expected or not isinstance(actual, str) or not consteq(expected, actual):
        return False
    if request:
        try:
            env["res.device.log"]._update_device(request)
        except Exception:
            _logger.warning(
                "Device-log update failed for a valid session; keeping the "
                "session authenticated",
                exc_info=True,
            )
    return True

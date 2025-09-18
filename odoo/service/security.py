import time
from typing import TYPE_CHECKING

from odoo.tools.misc import consteq

if TYPE_CHECKING:
    from odoo.api import Environment


def compute_session_token(session: object, env: Environment) -> str:
    """Compute the HMAC session token for the given session."""
    self = env["res.users"].browse(session.uid)
    return self._compute_session_token(session.sid)


def check_session(
    session: object,
    env: Environment,
    request: object | None = None,
) -> bool:
    """Validate that the session token matches the expected value.

    Expires deleted sessions, verifies the HMAC-based session token
    using constant-time comparison, and updates the device log on success.
    """
    session._delete_old_sessions()
    # Make sure we don't use a deleted session that can be saved again
    if "deletion_time" in session and session["deletion_time"] <= time.time():
        return False
    user = env["res.users"].browse(session.uid)
    expected = user._compute_session_token(session.sid)
    if not expected or not consteq(expected, session.session_token):
        return False
    if request:
        env["res.device.log"]._update_device(request)
    return True

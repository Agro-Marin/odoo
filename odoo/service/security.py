import logging
import time
from typing import TYPE_CHECKING

from odoo.tools.misc import consteq

if TYPE_CHECKING:
    from odoo.api import Environment

_logger = logging.getLogger(__name__)


def compute_session_token(session: object, env: Environment) -> str | bool:
    """Compute the HMAC session token for the given session.

    Returns ``False`` when ``session.uid`` resolves to an empty recordset
    (deleted user, falsy uid) — ``_compute_session_token`` is annotated
    ``str | bool`` for the same reason.  Callers MUST check the return type
    before storing it on a session.
    """
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
    # Single source of truth for the token computation (shared with callers
    # that store the token, e.g. web login / report rendering).  Returns
    # ``False`` for a deleted/falsy uid.
    expected = compute_session_token(session, env)
    # Both operands must be non-empty strings before reaching consteq:
    # consteq (and the underlying hmac.compare_digest) raises TypeError on
    # None/bool, which would convert a corrupted-session error into a 500.
    actual = session.session_token
    if not expected or not isinstance(actual, str) or not consteq(expected, actual):
        return False
    if request:
        # Device-log bookkeeping is non-essential to authentication: the token
        # already validated, so the session IS valid.  A failure updating the
        # device log (lock contention, a transient DB error, a serialization
        # conflict) must not reject it — the caller
        # (``ir_http._authenticate_explicit``) converts *any* exception raised
        # here into ``AccessDenied``, which would spuriously log out a valid user
        # and swallow a retryable conflict before ``retrying`` could act on it.
        # Log and continue.
        try:
            env["res.device.log"]._update_device(request)
        except Exception:
            _logger.warning(
                "Device-log update failed for a valid session; keeping the "
                "session authenticated",
                exc_info=True,
            )
    return True

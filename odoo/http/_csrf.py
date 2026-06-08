"""CSRF token utilities for :class:`~odoo.http.Request`.

Mixed into Request via :class:`_RequestCsrfMixin`. Tokens are HMAC-SHA256
of ``f"{sid_static_prefix}{max_ts}"``, formatted as ``{hexdigest}o{max_ts}``.
The static prefix (first :data:`STORED_SESSION_BYTES` chars of the sid)
survives soft-rotation, so a token issued before rotation remains valid
afterwards. ``max_ts`` rolls daily under the default 1-year time-limit,
giving each user a per-day salt that defeats BREACH-style attacks.
"""

from __future__ import annotations

import hashlib
import hmac
import time

from odoo.tools import consteq

from .constants import CSRF_TOKEN_MAX_AGE, STORED_SESSION_BYTES


class _RequestCsrfMixin:
    """CSRF token issuance and validation for :class:`Request`.

    Reads ``self.session``, ``self.env``. Has no state.
    """

    def csrf_token(self, time_limit: int | None = None) -> str:
        """
        Generates and returns a CSRF token for the current session.

        :param int | None time_limit: validity duration in seconds. When
            ``None`` (the default), :data:`~odoo.http.CSRF_TOKEN_MAX_AGE`
            (one year) is used; the embedded ``max_ts`` rolls daily
            under that distant expiry and effectively acts as a per-user
            salt against BREACH-style attacks. In practice the token
            outlives the session, so session expiry — not the CSRF
            ``max_ts`` — is what limits the token's useful life. Pass
            a small int (e.g. ``3600``) for sensitive forms that need a
            tighter window.
        :returns: ASCII token string
        :rtype: str
        """
        secret = self.env["ir.config_parameter"].sudo().get_param("database.secret")
        if not secret:
            msg = "CSRF protection requires a configured database secret"
            raise ValueError(msg)

        # if no `time_limit` => distant 1y expiry so max_ts acts as salt, e.g. vs BREACH
        max_ts = int(time.time() + (time_limit or CSRF_TOKEN_MAX_AGE))
        msg = f"{self.session.sid[:STORED_SESSION_BYTES]}{max_ts}".encode()

        hm = hmac.new(secret.encode("ascii"), msg, hashlib.sha256).hexdigest()
        return f"{hm}o{max_ts}"

    def validate_csrf(self, csrf: str | None) -> bool:
        """
        Is the given csrf token valid ?

        :param str csrf: The token to validate.
        :returns: ``True`` when valid, ``False`` when not.
        :rtype: bool
        """
        if not csrf:
            return False

        secret = self.env["ir.config_parameter"].sudo().get_param("database.secret")
        if not secret:
            msg = "CSRF protection requires a configured database secret"
            raise ValueError(msg)

        hm, _, max_ts = csrf.rpartition("o")
        if not max_ts:
            return False
        try:
            if int(max_ts) < int(time.time()):
                return False
        except ValueError:
            return False

        msg = f"{self.session.sid[:STORED_SESSION_BYTES]}{max_ts}".encode()
        hm_expected = hmac.new(secret.encode("ascii"), msg, hashlib.sha256).hexdigest()
        return consteq(hm, hm_expected)

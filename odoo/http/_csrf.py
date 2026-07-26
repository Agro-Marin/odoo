"""CSRF token utilities for :class:`~odoo.http.Request`.

Mixed into Request via :class:`_RequestCsrfMixin`. Tokens are HMAC-SHA256 of
``f"{sid_static_prefix}{max_ts}"``, formatted as ``{hexdigest}o{max_ts}``. The
static prefix (first :data:`STORED_SESSION_BYTES` sid chars) survives soft
rotation, so a token stays valid across it. ``max_ts`` (``int(now + time_limit)``)
changes on every issuance, salting each token against BREACH-style attacks.
"""

from __future__ import annotations

import hashlib
import hmac
import time

from odoo.tools import consteq

from ._protocols import RequestState
from .constants import CSRF_TOKEN_MAX_AGE, STORED_SESSION_BYTES


class _RequestCsrfMixin(RequestState):
    """CSRF token issuance and validation for :class:`Request`.

    The ``Request`` state it reads is declared by
    :class:`~odoo.http._protocols.RequestState`. Issuing a token via
    :meth:`csrf_token` marks the session dirty (``touch``) so its sid is
    persisted and survives to the validating request; :meth:`validate_csrf`
    has no side effects.
    """

    def csrf_token(self, time_limit: int | None = None) -> str:
        """
        Generate and return a CSRF token for the current session.

        :param int | None time_limit: validity duration in seconds.
            Defaults to :data:`~odoo.http.CSRF_TOKEN_MAX_AGE` (one year), so
            session expiry — not ``max_ts`` — limits the token in practice.
            Pass a small int (e.g. ``3600``) for sensitive forms.
        :returns: ASCII token string
        :rtype: str
        """
        secret = self.env["ir.config_parameter"].sudo().get_param("database.secret")
        if not secret:
            msg = "CSRF protection requires a configured database secret"
            raise ValueError(msg)

        max_ts = int(time.time() + (time_limit or CSRF_TOKEN_MAX_AGE))
        msg = f"{self.session.sid[:STORED_SESSION_BYTES]}{max_ts}".encode()

        hm = hmac.new(secret.encode("ascii"), msg, hashlib.sha256).hexdigest()

        if self.session.is_new:
            self.session.touch()
        return f"{hm}o{max_ts}"

    def validate_csrf(self, csrf: str | None) -> bool:
        """
        Is the given csrf token valid?

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

        if not hm.isascii():
            return False

        msg = f"{self.session.sid[:STORED_SESSION_BYTES]}{max_ts}".encode()
        hm_expected = hmac.new(secret.encode("ascii"), msg, hashlib.sha256).hexdigest()
        return consteq(hm, hm_expected)

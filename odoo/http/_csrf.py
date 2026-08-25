from __future__ import annotations

import hashlib
import hmac
import time

from odoo.tools import consteq

from ._protocols import RequestState
from .constants import CSRF_TOKEN_MAX_AGE, STORED_SESSION_BYTES


class _RequestCsrfMixin(RequestState):
    def csrf_token(self, time_limit: int | None = None) -> str:
        secret = self.env["ir.config_parameter"].sudo().get_param("database.secret")
        if not secret:
            msg = "CSRF protection requires a configured database secret"
            raise ValueError(msg)

        # `is None`, not `or`: 0 is a valid offset meaning "expire now",
        # and `or` cannot tell it from an omitted argument.
        if time_limit is None:
            time_limit = CSRF_TOKEN_MAX_AGE
        max_ts = int(time.time() + time_limit)
        msg = f"{self.session.sid[:STORED_SESSION_BYTES]}{max_ts}".encode()

        hm = hmac.new(secret.encode("ascii"), msg, hashlib.sha256).hexdigest()

        if self.session.is_new:
            self.session.touch()
        return f"{hm}o{max_ts}"

    def validate_csrf(self, csrf: str | None) -> bool:
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

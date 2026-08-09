"""The HTTP transport's :class:`~odoo.service.transaction.RetryParticipant`.

``retrying()`` may run a handler more than once, and a replayed HTTP handler
needs transport state that the first run consumed: a session object that is
still valid after the rollback, and uploaded file streams rewound to position
zero. This module holds that knowledge, so ``service/transaction.py`` does not
have to.

It is installed on import of ``odoo.http`` (see that package's ``__init__``),
the same injection shape ``orm/runtime/savepoint.py`` uses to give ``db/`` its
flushing savepoint without ``db/`` importing the ORM (ADR-0003).
"""

from __future__ import annotations

import typing

import odoo.service.transaction as _transaction
from odoo.service.transaction import RetryParticipant

from .core import request as _current_request
from .helpers import rewind_uploaded_files


class RequestRetryParticipant:
    """Restores one in-flight :class:`Request` for a replay."""

    __slots__ = ("_request",)

    def __init__(self, request: typing.Any) -> None:
        self._request = request

    def on_rollback(self, exc: BaseException) -> None:
        request = self._request
        current_sid = getattr(request.session, "sid", None)
        request.session = request._get_session_and_dbname(sid=current_sid)[0]

    def on_retry(self, exc: BaseException) -> None:
        request = self._request
        rewind_uploaded_files(request.httprequest, cause=exc)
        reset = getattr(request, "_reset_for_replay", None)
        if reset is not None:
            reset()

    def suppresses_uncommitted_warning(self) -> bool:
        # `getattr` rather than attribute access: this runs on the tail of
        # every served request, and `request` is not always a real `Request`
        # (tests patch it, `borrow_request` swaps it). Missing the warning on
        # such a stand-in is a far smaller failure than raising from here.
        return bool(getattr(self._request, "database_detached", False))


def current_request_participant() -> RetryParticipant | None:
    """The participant for the request in flight, or ``None`` off-request."""
    request = _current_request
    if not request:
        return None
    return RequestRetryParticipant(request)


_transaction.current_retry_participant = current_request_participant

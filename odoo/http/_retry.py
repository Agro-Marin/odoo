from __future__ import annotations

import typing

from .helpers import rewind_uploaded_files


class RequestRetryParticipant:
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

    def is_uncommitted_warning_suppressed(self) -> bool:
        return bool(getattr(self._request, "database_detached", False))

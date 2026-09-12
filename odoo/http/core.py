import contextlib
from typing import TYPE_CHECKING

import werkzeug.local

from odoo.libs.debug_log import DebugLog

if TYPE_CHECKING:
    from collections.abc import Generator

    from .request_class import Request

_debug = DebugLog(__name__)

_request_stack: werkzeug.local.LocalStack[Request] = werkzeug.local.LocalStack()
request: Request = _request_stack()


@contextlib.contextmanager
def borrow_request() -> Generator[Request | None]:
    req = _request_stack.pop()
    _debug.lifecycle("http.request.borrowed", present=req is not None)
    try:
        yield req
    finally:
        if req is not None:
            _request_stack.push(req)

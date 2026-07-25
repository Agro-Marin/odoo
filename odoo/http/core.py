import contextlib
from typing import TYPE_CHECKING

import werkzeug.local

if TYPE_CHECKING:
    from collections.abc import Generator

    from .request_class import Request

_request_stack: werkzeug.local.LocalStack[Request] = werkzeug.local.LocalStack()
request: Request = _request_stack()


@contextlib.contextmanager
def borrow_request() -> Generator[Request | None]:
    """Get the current request and unexpose it from the local stack.

    Yields ``None`` when there is no active request. The push-back is
    skipped in that case so the stack does not accumulate ``None`` entries
    over the lifetime of the process.
    """
    req = _request_stack.pop()
    try:
        yield req
    finally:
        if req is not None:
            _request_stack.push(req)

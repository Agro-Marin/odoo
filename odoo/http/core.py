import contextlib
from typing import TYPE_CHECKING

import werkzeug.local

if TYPE_CHECKING:
    from collections.abc import Generator

    from .request_class import Request

# Thread local global request object
_request_stack: werkzeug.local.LocalStack[Request] = werkzeug.local.LocalStack()
request: Request = _request_stack()


@contextlib.contextmanager
def borrow_request() -> Generator[Request]:
    """Get the current request and unexpose it from the local stack."""
    req = _request_stack.pop()
    try:
        yield req
    finally:
        _request_stack.push(req)

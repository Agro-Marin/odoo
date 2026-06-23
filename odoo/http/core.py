import contextlib
from typing import TYPE_CHECKING

import werkzeug.local

if TYPE_CHECKING:
    from collections.abc import Generator

    from .request_class import Request

# Thread-local global request object.
#
# ``request`` is a :class:`werkzeug.local.LocalProxy` resolving to the top of
# ``_request_stack`` on each access; at runtime it is **never** ``None``. The
# ``Request`` annotation is a type-checker hint (so callers skip casts), not a
# runtime assertion. Detect "no active request" with truthiness (``if request``
# — falsy when the stack is empty), never ``request is None`` (always False).
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

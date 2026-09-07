from functools import wraps

from odoo.exceptions import UserError


def spreadsheet_safe_batch(func):
    """Isolate a failing request inside a batched spreadsheet endpoint.

    The client groups the requests of many formulas into a single RPC and no
    longer retries them one by one, so keeping one bad request from costing
    the whole batch its answer is the server's job. The batch runs as a whole
    first, so the ORM still prefetches across all of it, and is only replayed
    request by request once that raises. The failing entry is answered with
    ``{"__error__": message}`` in its place.

    Only ``UserError`` is isolated: everything under it (``AccessError``,
    ``MissingError``, ``ValidationError``) is a per-request problem the caller
    can act on, while anything else is a bug and must reach the client as a
    failed call.
    """

    @wraps(func)
    def wrapper(self, requests):
        try:
            return func(self, requests)
        except UserError:
            results = []
            for request in requests:
                try:
                    results.append(func(self, [request])[0])
                except UserError as error:
                    results.append({"__error__": str(error)})
            return results

    return wrapper

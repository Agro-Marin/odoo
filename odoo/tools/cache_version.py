"""Content-hash stamping for cacheable read responses (Plan C).

Endpoints decorated here emit a ``__version`` sha256 hex digest that the
client-side rpc cache
(``addons/core/addons/web/static/src/core/network/rpc_cache.js``
``payloadChanged``) compares in O(1) instead of running the default
``JSON.stringify(prev) !== JSON.stringify(curr)`` deep compare on every
``update: "always"`` revalidation.

Two decorator forms cover all return shapes:

- :func:`versioned` mutates the result in place — for methods returning a
  ``dict``.  The ``__version`` key rides as a regular payload field.
- :func:`versioned_envelope` stashes the hash on
  ``http.request._response_version`` — for methods returning a ``list``,
  a scalar, or anything where there is no in-payload key to attach.  The
  JSON-RPC dispatcher (``core/odoo/http/dispatcher.py`` ``_response``)
  lifts the side-channel value to a ``version`` sibling of ``result`` in
  the envelope.  The JS rpc layer (``rpc.js``) re-attaches it as
  ``result.__version`` so the client cache sees the same field name in
  both cases.

The hash uses ``sort_keys=True`` so the digest is invariant under Python
dict insertion order — two interpreter runs over the same query can
yield different insertion orders and the version must stay stable
across them.  ``default=str`` lets the canonical-JSON pass survive
non-JSON-native values (datetimes, sets, Decimals, etc.) that may appear
in intermediate structures.

See ``addons/core/addons/web/machine_doc_v1/STATE_MANAGEMENT.md``
"Server-side ``__version`` stamp" for the full contract, currently
opted-in endpoints, and rollout history.
"""

import hashlib
import json
from functools import wraps

__all__ = ["versioned", "versioned_envelope"]


def _canonical_sha256(value):
    """Return the SHA-256 hex digest of ``value`` serialized to canonical JSON.

    ``sort_keys=True`` makes the digest invariant under Python dict insertion
    order.  ``default=str`` lets the pass survive non-JSON-native values
    (datetimes, sets, Decimals, etc.) that may appear in intermediate
    structures.  ``separators=(",", ":")`` strips whitespace for minimum
    serialized size — the digest is byte-identical to what
    ``JSON.stringify(JSON.parse(canonical))`` produces in V8 (verified in
    the Phase 1 cross-language test).
    """
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            default=str,
            separators=(",", ":"),
        ).encode(),
    ).hexdigest()


def versioned(method):
    """Inject ``__version`` (sha256 of canonical JSON) into dict returns.

    No-op for non-dict returns and for dicts that already carry a
    ``__version`` key (idempotent — lets a method opt out by setting the
    field explicitly).  For list / scalar returns use ``versioned_envelope``.
    """
    @wraps(method)
    def wrapper(*args, **kwargs):
        result = method(*args, **kwargs)
        if isinstance(result, dict) and "__version" not in result:
            result["__version"] = _canonical_sha256(result)
        return result
    return wrapper


def versioned_envelope(method):
    """Stash a ``__version`` hash for list / scalar returns via a side channel.

    The dict-mutating :func:`versioned` approach does not work for methods
    that return a ``list`` (no place to attach a key) or a scalar.  Instead,
    this decorator stamps the hash onto the active HTTP request as
    ``request._response_version``; the JSON-RPC dispatcher
    (``core/odoo/http/dispatcher.py`` ``_response``) reads it and adds a
    ``version`` sibling to the JSON-RPC envelope alongside ``result``.

    The JS rpc layer (``rpc.js``) lifts the sibling back onto the result
    object so the client cache sees the same ``__version`` field whether
    the server used :func:`versioned` (in-payload) or
    :func:`versioned_envelope` (out-of-band).

    Outside an HTTP request (cron jobs, internal Python callers, test
    fixtures) the side channel is unavailable and the decorator silently
    no-ops — the result is returned unmodified.
    """
    @wraps(method)
    def wrapper(*args, **kwargs):
        result = method(*args, **kwargs)
        try:
            from odoo.http import request
            request._response_version = _canonical_sha256(result)
        except RuntimeError:
            # No active HTTP request — internal caller or background task.
            pass
        except ModuleNotFoundError:
            # Standalone Python (no Odoo registry loaded); defensive only —
            # the decorator should never be live in such a context.
            pass
        return result
    return wrapper

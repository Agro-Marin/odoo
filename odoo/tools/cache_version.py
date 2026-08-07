"""Content-hash stamping for cacheable read responses.

Decorated endpoints emit a ``__version`` content hex digest that the client-side
rpc cache (``web/static/src/core/network/rpc_cache.js`` ``payloadChanged``)
compares in O(1) instead of the default ``JSON.stringify`` deep compare on every
``update: "always"`` revalidation.

Two decorator forms cover all return shapes:

- :func:`versioned` — for ``dict`` returns; the ``__version`` key rides as a
  regular payload field.
- :func:`versioned_envelope` — for ``list``/scalar returns with no in-payload
  key to attach. It stashes the hash on ``http.request._response_version``; the
  JSON-RPC dispatcher (``core/odoo/http/dispatcher.py`` ``_response``) lifts it
  to a ``version`` sibling of ``result``, and the JS rpc layer (``rpc.js``)
  re-attaches it as ``result.__version`` so the client sees the same field name
  in both cases.

Digests use sorted keys (insertion-order invariant) and ``default=str`` to
survive non-JSON-native values (datetimes, sets, Decimals). See
``addons/core/addons/web/machine_doc_v1/STATE_MANAGEMENT.md`` "Server-side
``__version`` stamp" for the full contract, opted-in endpoints, and history.
"""

import json
from functools import wraps

import orjson

from odoo.libs.hashing import cache_hash

__all__ = ["versioned", "versioned_envelope"]

_CANONICAL_OPT = orjson.OPT_SORT_KEYS | orjson.OPT_PASSTHROUGH_DATETIME


def _canonical_default(value):
    """``default`` hook for the canonical-JSON pass, shared by the orjson and
    stdlib paths so both coerce non-native values identically.

    ``set``/``frozenset`` are emitted as a **deterministically ordered** array:
    their native iteration order depends on ``PYTHONHASHSEED`` (randomized per
    process), so the previous ``str(set)`` coercion made two workers emit
    different digests for identical data — silently defeating the client cache
    for any endpoint returning a set. Sorting by each element's own canonical
    bytes gives a total, cross-process-stable order for arbitrary element types.
    Everything else keeps the historical ``str()`` coercion.
    """
    if isinstance(value, (set, frozenset)):
        return sorted(value, key=_canonical_bytes)
    return str(value)


def _canonical_bytes(value):
    """Serialize ``value`` to canonical JSON bytes: sorted keys, compact
    separators, ``str``-coerced for non-native types.

    Sorted keys make the digest invariant under dict insertion order. See
    :data:`_CANONICAL_OPT` for the byte-compatibility contract with the previous
    stdlib implementation.
    """
    try:
        return orjson.dumps(value, option=_CANONICAL_OPT, default=_canonical_default)
    except orjson.JSONEncodeError, TypeError:
        return json.dumps(
            value, sort_keys=True, default=_canonical_default, separators=(",", ":")
        ).encode()


def _canonical_digest(value):
    """Return the hex digest of ``value``'s canonical JSON form.

    The algorithm is whatever :mod:`odoo.libs.hashing` selected (BLAKE3, else
    sha256) — both are 64 hex chars, and the client only ever compares two
    server-emitted digests (``rpc_cache.js`` never recomputes one), so a change
    of algorithm costs one self-healing cache refresh, exactly like the
    serialization change documented above.
    """
    return cache_hash(_canonical_bytes(value))


def versioned(method):
    """Inject ``__version`` (digest of canonical JSON) into dict returns.

    No-op for non-dict returns and for dicts that already carry a
    ``__version`` key (idempotent — lets a method opt out by setting the
    field explicitly).  For list / scalar returns use ``versioned_envelope``.
    """

    @wraps(method)
    def wrapper(*args, **kwargs):
        result = method(*args, **kwargs)
        if isinstance(result, dict) and "__version" not in result:
            result = {**result, "__version": _canonical_digest(result)}
        return result

    return wrapper


def versioned_envelope(method):
    """Stash a ``__version`` hash for list / scalar returns via a side channel.

    Stamps the hash onto the active HTTP request as ``request._response_version``
    (see the module docstring for how it reaches the client). Outside an HTTP
    request — cron jobs, internal callers, tests — the side channel is
    unavailable and the decorator no-ops, returning the result unmodified.
    """

    @wraps(method)
    def wrapper(*args, **kwargs):
        result = method(*args, **kwargs)
        try:
            from odoo.http import request
        except ModuleNotFoundError:
            return result
        if request:
            request._response_version = _canonical_digest(result)
        return result

    return wrapper

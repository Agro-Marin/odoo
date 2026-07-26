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

from .hashing import cache_hash

__all__ = ["versioned", "versioned_envelope"]

# orjson (Rust) replaces stdlib ``json`` for the canonical-JSON pass: ~3.5x
# faster on the C-encoder path and much more on the pure-Python ``iterencode``
# path that ``default=str`` can trigger (this hash showed up as ~11% of a
# ``web_search_read`` request in profiling).  The pass stays byte-identical to
# the historical stdlib output for the value space these endpoints actually
# emit — str-keyed dicts of finite JSON scalars, ASCII or not — so cached
# client digests are unaffected:
#   * OPT_SORT_KEYS            — key-order invariance (was ``sort_keys=True``).
#   * OPT_PASSTHROUGH_DATETIME — route datetime/date/time to ``default=str`` so
#     they serialize as ``str(value)`` exactly like stdlib did, not orjson's
#     native ``T``-separated RFC-3339 form.
#   * default=str              — unchanged: survive non-JSON-native values.
# orjson always emits compact ``(",", ":")`` separators (matching the old
# ``separators=``) and UTF-8.  Three encodings move toward standard-JSON / V8
# ``JSON.stringify`` semantics and so differ from the old stdlib bytes:
#   - non-ASCII string values  → UTF-8 instead of ``\uXXXX`` escapes;
#   - non-finite floats        → ``null`` instead of ``Infinity``/``NaN``;
#   - exponent-notation floats → e.g. ``1e-7`` instead of ``1e-07``.
# These change the digest only for payloads that contain such values and are
# safe: the JS rpc cache compares two *server-emitted* hashes and never
# recomputes one client-side (rpc_cache.js), so the only effect is a one-time,
# self-healing cache refresh after deploy.  Values orjson refuses outright
# (non-str dict keys, ints beyond 64-bit) fall back to stdlib, which both keeps
# their historical digest and guarantees this never raises inside a response.
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
        # orjson refuses non-str dict keys and ints beyond the 64-bit range;
        # stdlib accepts both and yields the historical digest.  Falling back
        # keeps those payloads byte-identical AND ensures this helper never
        # raises inside the response-stamping decorators below.
        return json.dumps(
            value, sort_keys=True, default=_canonical_default, separators=(",", ":")
        ).encode()


def _canonical_digest(value):
    """Return the hex digest of ``value``'s canonical JSON form.

    The algorithm is whatever :mod:`odoo.tools.hashing` selected (BLAKE3, else
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
            # Copy before stamping: the digest is derived from ``result``'s
            # contents, so writing it back into the same object would (a) corrupt
            # the object if the method returned a shared/cached dict -- injecting
            # ``__version`` into the cached value, whose documented "already has
            # ``__version`` -> no-op" branch would then pin that first digest
            # forever -- and (b) mean the returned dict no longer hashes to its
            # own stamp.  A shallow copy is enough; only the top level gains a key.
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
            # Standalone Python (no Odoo registry loaded); defensive only —
            # the decorator should never be live in such a context.
            return result
        # Compute the digest only when there is a request to stash it on:
        # ``bool(request)`` is False (never raises) for cron jobs, internal
        # callers and tests, so the potentially expensive hash of a large
        # ``result`` is skipped entirely off the HTTP path instead of being
        # computed and discarded.
        if request:
            request._response_version = _canonical_digest(result)
        return result

    return wrapper

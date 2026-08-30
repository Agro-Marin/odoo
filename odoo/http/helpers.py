import contextlib
import functools
import logging
import re
import traceback
from collections.abc import Callable, Iterable, Mapping
from typing import Any
from urllib.parse import quote as url_quote
from urllib.parse import urlsplit

import psycopg

import odoo.service.common
import odoo.service.db
import odoo.service.model
from odoo.db import is_maintenance_db
from odoo.libs.worker_thread import current_worker_thread
from odoo.tools import config

from .constants import SESSION_LIFETIME
from .core import borrow_request, request

_logger = logging.getLogger(__name__)


def content_disposition(filename: str, disposition_type: str = "attachment") -> str:
    if disposition_type not in ("attachment", "inline"):
        e = f"Invalid disposition_type: {disposition_type!r}"
        raise ValueError(e)
    return f"{disposition_type}; filename*=UTF-8''{url_quote(filename, safe='')}"


def rewind_uploaded_files(
    httprequest: Any, *, cause: BaseException | None = None
) -> None:
    for filename, file in httprequest.files.items(multi=True):
        if hasattr(file, "seekable") and file.seekable():
            file.seek(0)
        else:
            raise RuntimeError(
                f"Cannot retry request on input file {filename!r} after a "
                f"transaction error"
            ) from cause


# ``db_list`` below is the package's ONE database-listing entry point.
#
# Both readers of "which databases does this host serve" go through it: the
# selector and database manager (``web/controllers``), and
# ``Request._get_session_and_dbname`` resolving a session-less request to the
# single one. Those were two implementations with two caches and two error
# policies, which is why ``test_http``'s ``nodb_url_open`` had to patch four names
# to say "no database".
#
# There is no cache HERE, and that is the point. ``service.db.list_dbs`` already
# memoises the ``pg_database`` scan behind a lock, with its own TTL, its own
# invalidation on every catalogue mutation this process makes, and a fresh list
# per caller. A second TTL cache used to sit on top of it, keyed on
# ``(time_bucket, force)``, and it bought nothing: it added a second staleness
# window on top of the first, registered a second listener for the same
# invalidation, and made ``force`` a lie -- ``db_list(force=True)`` answered from
# up to five seconds ago, which is why ``_serve._acquire_registry_cursor`` had one
# of its two reasons to reach PAST this function to ``service.db.list_dbs``. That
# reason is gone; its other one stands, and is why it still does: after a registry
# failure it asks whether the database exists AT ALL, which the host filter below
# would answer wrongly for a database that exists and is filtered out.
#
# Filtering stays outside any cache regardless, because ``db_filter`` falls back
# to the *current request's* Host header when ``host`` is None, and that must not
# be memoised.


def clear_db_list_cache() -> None:
    # Kept as the name the package (and ``test_http``, as ``clear_monodb_cache``)
    # calls, now that the cache it used to clear is gone: the one that remains is
    # ``service.db``'s, and this is how http asks for it to be dropped.
    odoo.service.db.invalidate_catalog_caches()


def db_list(force: bool = False, host: str | None = None) -> list[str]:
    try:
        dbs = odoo.service.db.list_dbs(force)
    except psycopg.Error:
        _logger.warning(
            "Could not list databases; answering as though this instance serves none.",
            exc_info=True,
        )
        return []
    return db_filter(dbs, host)


def _normalize_dbfilter_host(host: str) -> str:
    if host.startswith("["):
        end = host.find("]")
        if end != -1:
            host = host[: end + 1]
        return host.lower()
    return host.partition(":")[0].lower().removeprefix("www.")


@functools.lru_cache(maxsize=8)
def _dbfilter_reads_the_host(pattern: str) -> bool:
    return "%h" in pattern or "%d" in pattern


@functools.lru_cache(maxsize=512)
def _compiled_dbfilter(pattern: str, host: str) -> re.Pattern[str]:
    # `host` reaches here from the Host header, which werkzeug does not
    # validate (`trusted_hosts` is None) -- so it is an attacker-chosen cache
    # key, and 600 distinct hosts evict all 512 entries and make every
    # legitimate request recompile. Callers pass "" unless the pattern
    # actually interpolates the host, which collapses the common case
    # (`dbfilter = .*`, and every pattern naming databases outright) to a
    # single entry no header can displace.
    #
    # A pattern that DOES use %h/%d still compiles per host: the host is part
    # of the regex text there, so there is nothing to hoist. That is the
    # narrow residue, and it is bounded by `maxsize` rather than removed.
    domain = host.partition(".")[0]
    return re.compile(
        pattern.replace("%h", re.escape(host)).replace("%d", re.escape(domain))
    )


def db_filter(dbs: Iterable[str], host: str | None = None) -> list[str]:
    # Two filters, applied in order, and the input's order is preserved through
    # both. The `db_name` filter used to be spelled twice -- once inside the
    # `dbfilter` branch and once as `sorted(set(db_name) & dbs)` for the branch
    # without one -- so the selector listed databases in the catalogue's order
    # with a dbfilter set and in sorted order without one, from the same list.
    # `service.db._query_catalogue` already orders by datname, so preserving the
    # input is what makes the two agree.
    names = [db for db in dbs if not is_maintenance_db(db)]

    pattern = config["dbfilter"]
    if pattern:
        if _dbfilter_reads_the_host(pattern):
            if host is None:
                host = (
                    request.httprequest.environ.get("HTTP_HOST", "") if request else ""
                )
            host = _normalize_dbfilter_host(host)
        else:
            host = ""
        dbfilter_re = _compiled_dbfilter(pattern, host)
        names = [db for db in names if dbfilter_re.match(db)]

    if config["db_name"]:
        exposed = set(config["db_name"])
        names = [db for db in names if db in exposed]

    return names


def _get_rpc_dispatcher(service_name: str) -> Callable:
    match service_name:
        case "common":
            return odoo.service.common.dispatch
        case "db":
            return odoo.service.db.dispatch
        case "object":
            return odoo.service.model.dispatch
        case _:
            raise KeyError(service_name)


def _restore_thread_attr(thread: Any, attr: str, prev: Any, sentinel: Any) -> None:
    if prev is sentinel:
        with contextlib.suppress(AttributeError):
            delattr(thread, attr)
    else:
        setattr(thread, attr, prev)


def dispatch_rpc(service_name: str, method: str, params: Mapping[str, Any]) -> Any:
    thread = current_worker_thread()
    sentinel = object()
    prev_uid = getattr(thread, "uid", sentinel)
    prev_dbname = getattr(thread, "dbname", sentinel)
    with borrow_request():
        thread.uid = None
        thread.dbname = None
        try:
            dispatch = _get_rpc_dispatcher(service_name)
            return dispatch(method, params)
        finally:
            _restore_thread_attr(thread, "uid", prev_uid, sentinel)
            _restore_thread_attr(thread, "dbname", prev_dbname, sentinel)


def get_session_max_inactivity(env: Any) -> int:
    if env is None or env.cr.closed:
        return SESSION_LIFETIME

    ICP = env["ir.config_parameter"].sudo()

    try:
        value = int(ICP.get_param("sessions.max_inactivity_seconds", SESSION_LIFETIME))
        if value <= 0:
            _logger.warning(
                "Non-positive value for 'sessions.max_inactivity_seconds' "
                "(%r), using default value.",
                value,
            )
            return SESSION_LIFETIME
        return value
    except ValueError:
        _logger.warning(
            "Invalid value for 'sessions.max_inactivity_seconds', using default value."
        )
        return SESSION_LIFETIME
    except psycopg.Error:
        _logger.debug(
            "Could not read session max inactivity from DB, using default.",
            exc_info=True,
        )
        return SESSION_LIFETIME


def is_cors_preflight(request: Any, endpoint: Any) -> bool:
    return request.httprequest.method == "OPTIONS" and bool(
        endpoint.routing.get("cors", False)
    )


def _origin_parts(url: str) -> tuple[str, str, int | None] | None:
    try:
        parts = urlsplit(url)
    except ValueError:
        # `urlsplit` raises "Invalid IPv6 URL" on an unbalanced bracket, and the
        # Origin header is whatever the client sent -- `Origin: http://[` is one
        # curl away from a 500 on every CORS route.
        return None
    if not parts.hostname:
        return None
    try:
        port = parts.port
    except ValueError:
        # `urlsplit` defers port validation to attribute access, so a netloc
        # like "127.0.0.1:8192.evil.com" yields hostname "127.0.0.1" and raises
        # only here. No browser can emit such an Origin -- a colon is not legal
        # in a hostname -- but a resolver that decides who may read a
        # credentialed response must not answer "same host" to a string it
        # could not parse.
        return None
    # Deliberately NOT normalising a missing port to the scheme default: the
    # scheme is the term we cannot trust (see below), so expanding through it
    # would make an undeclared TLS terminator look like a port mismatch.
    return parts.scheme, parts.hostname, port


def cors_same_host(request: Any) -> str | None:
    # "Same host" has to mean same ORIGIN, which is (scheme, host, port) -- this
    # compared hostname alone, so `http://app.example.com:9999` and
    # `https://app.example.com` were both "same host" as `http://app.example.com`
    # and got `Access-Control-Allow-Credentials: true`. Any other service on the
    # same hostname could therefore read a credentialed response.
    #
    # Port is compared strictly: both sides derive it from the Host header, which
    # a reverse proxy forwards, so it agrees in every deployment.
    #
    # Scheme is compared ONLY when we are already on https. A TLS terminator that
    # nobody declared with `proxy_mode` leaves `host_url` saying "http" while the
    # browser's Origin says "https" -- measured, not assumed -- and refusing that
    # would break a working deployment to close a hole we cannot see from here.
    # When `is_secure` does hold, an http Origin is a downgrade and is refused.
    origin = request.httprequest.headers.get("Origin")
    if not origin:
        return None
    theirs = _origin_parts(origin)
    ours = _origin_parts(request.httprequest.host_url)
    if theirs is None or ours is None:
        return None
    if theirs[1:] != ours[1:]:
        return None
    if theirs[0] != ours[0] and request.httprequest.is_secure:
        return None
    return origin


_TRACEBACK_HIDDEN = "Traceback hidden; enable dev_mode or read the server log."


def _hide_exception_internals() -> bool:
    return bool(request) and not config["dev_mode"]


def _exception_debug(exception: BaseException) -> str:
    if _hide_exception_internals():
        return _TRACEBACK_HIDDEN
    return "".join(traceback.format_exception(exception))


_OPAQUE_EXCEPTION_TYPES = (psycopg.Error, OSError)
_MASKED_EXCEPTION_MESSAGE = "Internal Server Error"


def serialize_exception(
    exception: BaseException,
    *,
    message: str | None = None,
    arguments: tuple | None = None,
) -> dict[str, Any]:
    name = type(exception).__name__
    module = type(exception).__module__
    opaque = (
        isinstance(exception, _OPAQUE_EXCEPTION_TYPES) and _hide_exception_internals()
    )

    if message is None:
        message = _MASKED_EXCEPTION_MESSAGE if opaque else str(exception)
    if arguments is None:
        arguments = () if opaque else exception.args

    return {
        "name": f"{module}.{name}" if module else name,
        "message": message,
        "arguments": arguments,
        "context": getattr(exception, "context", {}),
        "debug": _exception_debug(exception),
    }

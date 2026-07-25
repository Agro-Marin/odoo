import contextlib
import functools
import logging
import re
import threading
import traceback
from collections.abc import Callable, Iterable, Mapping
from typing import Any
from urllib.parse import quote as url_quote

import psycopg

import odoo.service.common
import odoo.service.db
import odoo.service.model
from odoo.tools import config

from .constants import SESSION_LIFETIME
from .core import borrow_request, request

_logger = logging.getLogger(__name__)


def content_disposition(filename: str, disposition_type: str = "attachment") -> str:
    """
    Craft a ``Content-Disposition`` header, see :rfc:`6266`.

    :param filename: The name of the file, should that file be saved on
        disk by the browser.
    :param disposition_type: Tell the browser what to do with the file,
        either ``"attachment"`` to save the file on disk,
        or ``"inline"`` to display the file.
    """
    if disposition_type not in ("attachment", "inline"):
        e = f"Invalid disposition_type: {disposition_type!r}"
        raise ValueError(e)
    return f"{disposition_type}; filename*=UTF-8''{url_quote(filename, safe='')}"


def rewind_uploaded_files(
    httprequest: Any, *, cause: BaseException | None = None
) -> None:
    """Seek every uploaded file back to offset 0 before a request is replayed.

    Once the body has been read, the werkzeug ``FileStorage`` streams in
    ``httprequest.files`` sit at EOF.  Any replay of the handler must rewind
    them or the second run reads an empty upload and silently drops the file.
    Two independent replay paths share this one primitive so they cannot drift:

    * the serialization-failure retry loop in
      :func:`odoo.service.transaction.retrying`, and
    * the read-only → read-write cursor upgrade in
      :meth:`odoo.http._serve._RequestServeMixin._rewind_input_files`.

    ``.items(multi=True)`` is REQUIRED, not cosmetic: a
    ``<input type="file" multiple>`` posts several files under one field name,
    and the default ``MultiDict.items()`` yields only the *first* entry per key
    — so every file after the first would be left at EOF and lost on replay
    (silent data loss, only under a retry).

    A non-seekable stream cannot be replayed, so this raises ``RuntimeError``
    (chained onto ``cause`` when given) rather than truncating the upload.
    """
    for filename, file in httprequest.files.items(multi=True):
        if hasattr(file, "seekable") and file.seekable():
            file.seek(0)
        else:
            raise RuntimeError(
                f"Cannot retry request on input file {filename!r} after a "
                f"transaction error"
            ) from cause


def db_list(force: bool = False, host: str | None = None) -> list[str]:
    """
    Get the list of available databases.

    :param bool force: See :func:`~odoo.service.db.list_dbs`:
    :param host: The Host used to replace %h and %d in the dbfilters
        regexp. Taken from the current request when omitted.
    :returns: the list of available databases
    :rtype: list[str]
    """
    try:
        dbs = odoo.service.db.list_dbs(force)
    except psycopg.Error:
        return []
    return db_filter(dbs, host)


def _normalize_dbfilter_host(host: str) -> str:
    """Reduce a raw ``Host`` header to the form the dbfilter regex matches:
    strip ``:port``, lowercase, then strip one leading ``www.``.

    NOT idempotent (``www.www.x`` loses one ``www.`` per application), so it
    must run exactly once per Host — :func:`db_filter` applies it before the
    :func:`_compiled_dbfilter` lookup, and nothing else may re-apply it.
    Collapsing equivalent spellings (``www.example.com``, ``example.com:443``,
    ``EXAMPLE.com``) onto one :func:`_compiled_dbfilter` entry both routes a
    case-insensitive Host (RFC 4343) to the same database and prevents an
    attacker-varied Host from amplifying the regex cache — the same vector
    :data:`DB_MONODB_CACHE_TTL` closes for the catalog read. Lowercasing precedes
    ``removeprefix`` so an upper-case ``WWW.`` is stripped too.

    A bracketed IPv6 literal (RFC 3986: ``[::1]:8069``) keeps its brackets and
    loses only the port — a bare ``partition(":")`` would truncate it to ``[``,
    so no dbfilter ``%h`` could ever match an IPv6 Host.
    """
    if host.startswith("["):
        end = host.find("]")
        if end != -1:
            host = host[: end + 1]
        return host.lower()
    return host.partition(":")[0].lower().removeprefix("www.")


@functools.lru_cache(maxsize=512)
def _compiled_dbfilter(pattern: str, host: str) -> re.Pattern[str]:
    """Compile and cache the dbfilter regex for one ``(pattern, host)`` pair.

    :func:`db_filter` runs on nearly every request; the compiled regex depends
    only on the ``dbfilter`` pattern and host, so memoise it. ``pattern`` is in
    the key so config changes are honoured; ``maxsize`` bounds memory. ``host``
    MUST already be normalised (see :func:`_normalize_dbfilter_host`) — the sole
    caller, :func:`db_filter`, does so before the cache lookup; re-normalising
    here would strip a second ``www.`` from a ``www.www.*`` Host.
    """
    domain = host.partition(".")[0]
    return re.compile(
        pattern.replace("%h", re.escape(host)).replace("%d", re.escape(domain))
    )


def db_filter(dbs: Iterable[str], host: str | None = None) -> list[str]:
    """
    Return the subset of ``dbs`` that match the dbfilter and/or the dbname
    server configuration. In case neither are configured, return ``dbs``
    as-is.

    When both are set, ``--database`` (``db_name``) is an explicit allowlist that
    *further constrains* the ``dbfilter`` result — not a mutually-exclusive
    alternative. Otherwise a permissive ``dbfilter`` (``.*``) would re-expose
    databases the operator pinned away with ``-d``, making a multi-db host
    resolve ambiguously (``db_monodb`` → ``None``) so every db-bound route 404s.

    Result ordering depends on which mode is active:

    * ``dbfilter`` set (optionally with ``db_name``) → preserves the input order
      of ``dbs`` (itself the order from :func:`~odoo.service.db.list_dbs`).
    * ``db_name`` set (no ``dbfilter``) → sorted alphabetically.
    * Neither set → preserves the input order.

    Callers that need a stable, mode-independent order should sort the
    result themselves.

    :param Iterable[str] dbs: The list of database names to filter.
    :param host: The Host used to replace %h and %d in the dbfilters
        regexp. Taken from the current request when omitted.
    :returns: The original list filtered.
    :rtype: list[str]
    """
    protected_dbs = odoo.service.db.SYSTEM_DBS | {config["db_template"]}
    dbs = [db for db in dbs if db not in protected_dbs]
    if config["dbfilter"]:
        if host is None:
            host = request.httprequest.environ.get("HTTP_HOST", "") if request else ""
        host = _normalize_dbfilter_host(host)
        dbfilter_re = _compiled_dbfilter(config["dbfilter"], host)
        dbs = [db for db in dbs if dbfilter_re.match(db)]
        if config["db_name"]:
            exposed = set(config["db_name"])
            dbs = [db for db in dbs if db in exposed]
        return dbs

    if config["db_name"]:
        return sorted(set(config["db_name"]).intersection(dbs))

    return dbs


def _get_rpc_dispatcher(service_name: str) -> Callable:
    """Map an RPC service name to its dispatch function (KeyError on unknown)."""
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
    """Restore ``thread.attr`` to ``prev``, or delete it if it was absent before."""
    if prev is sentinel:
        with contextlib.suppress(AttributeError):
            delattr(thread, attr)
    else:
        setattr(thread, attr, prev)


def dispatch_rpc(service_name: str, method: str, params: Mapping[str, Any]) -> Any:
    """
    Perform a RPC call.

    :param str service_name: either "common", "db" or "object".
    :param str method: the method name of the given service to execute
    :param Mapping params: the keyword arguments for method call
    :return: the return value of the called method
    :rtype: Any
    """
    thread = threading.current_thread()
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
    """Get the maximum session inactivity time in seconds."""
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
    """Check if the request is a CORS preflight request.

    ``cors`` holds the allow-origin *string*, so ``bool(...)`` keeps the declared
    ``-> bool`` contract instead of leaking that value to callers.
    """
    return request.httprequest.method == "OPTIONS" and bool(
        endpoint.routing.get("cors", False)
    )


_TRACEBACK_HIDDEN = "Traceback hidden; enable dev_mode or read the server log."


def _hide_exception_internals() -> bool:
    """Whether serialized-exception internals must be hidden from the reader."""
    return bool(request) and not config["dev_mode"]


def _exception_debug(exception: BaseException) -> str:
    """The ``debug`` field of a serialized exception, gated for client responses.

    The full traceback (server paths, code structure) is included only when
    :func:`_hide_exception_internals` says the reader is trusted; otherwise it
    is replaced with a short note. Always a ``str``, and the full traceback
    still reaches the server log via ``Application.__call__``.
    """
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
    """Serialize an exception for a JSON response.

    For opaque infrastructure errors (:data:`_OPAQUE_EXCEPTION_TYPES`) serialized
    toward an untrusted client, the human ``message`` and ``arguments`` are
    replaced with a generic placeholder unless the caller passes them explicitly
    — a raw ``psycopg`` error must not disclose SQL/schema/row data, nor an
    ``OSError`` its filesystem paths. The full detail still reaches the server
    log via ``Application.__call__``.
    """
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

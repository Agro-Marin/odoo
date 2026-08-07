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


def db_list(force: bool = False, host: str | None = None) -> list[str]:
    try:
        dbs = odoo.service.db.list_dbs(force)
    except psycopg.Error:
        return []
    return db_filter(dbs, host)


def _normalize_dbfilter_host(host: str) -> str:
    if host.startswith("["):
        end = host.find("]")
        if end != -1:
            host = host[: end + 1]
        return host.lower()
    return host.partition(":")[0].lower().removeprefix("www.")


@functools.lru_cache(maxsize=512)
def _compiled_dbfilter(pattern: str, host: str) -> re.Pattern[str]:
    domain = host.partition(".")[0]
    return re.compile(
        pattern.replace("%h", re.escape(host)).replace("%d", re.escape(domain))
    )


def db_filter(dbs: Iterable[str], host: str | None = None) -> list[str]:
    dbs = [db for db in dbs if not is_maintenance_db(db)]
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


def cors_same_host(request: Any) -> str | None:
    origin = request.httprequest.headers.get("Origin")
    if not origin:
        return None
    if urlsplit(origin).hostname == urlsplit(request.httprequest.host_url).hostname:
        return origin
    return None


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

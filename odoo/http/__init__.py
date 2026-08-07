from .constants import (
    CORS_MAX_AGE,
    CSRF_TOKEN_MAX_AGE,
    DEFAULT_ALLOWED_METHODS,
    DEFAULT_LANG,
    DEFAULT_MAX_CONTENT_LENGTH,
    MISSING_CSRF_WARNING,
    NOT_FOUND_NODB,
    REJECTED_HTTP_METHODS,
    ROUTING_KEYS,
    SAFE_HTTP_METHODS,
    SESSION_DELETION_TIMER,
    SESSION_LIFETIME,
    SESSION_ROTATION_EXCLUDED_PATHS,
    SESSION_ROTATION_INTERVAL,
    STATIC_CACHE,
    STATIC_CACHE_LONG,
    STORED_SESSION_BYTES,
    get_default_session,
    register_ensure_db_paths,
    register_session_rotation_excluded_paths,
)

from .session import _session_identifier_re

from .exceptions import (
    RegistryError,
    SessionExpiredException,
)

from ._protocols import HttpExtension

from .helpers import (
    content_disposition,
    cors_same_host,
    db_filter,
    db_list,
    dispatch_rpc,
    get_session_max_inactivity,
    is_cors_preflight,
    rewind_uploaded_files,
    serialize_exception,
)

from .stream import Stream

from .controller import Controller

from .routing import (
    FasterRule,
    LazyCompiledBuilder,
    register_routing_parameters,
    route,
    rule_routing_kwargs,
    _generate_routing_rules,
    _check_and_complete_route_definition,
)

from .session import (
    FilesystemSessionStore,
    Session,
)

from .geoip import (
    GEOIP_EMPTY_CITY,
    GEOIP_EMPTY_COUNTRY,
    GeoIP,
    geoip2,
    maxminddb,
)

from .core import (
    _request_stack,
    request,
    borrow_request,
)

from .wrappers import (
    HTTPRequest,
    Response,
    FutureResponse,
    Headers,
    ResponseCacheControl,
    ResponseStream,
    _Response,
)

from .request_class import Request

from .dispatcher import (
    Dispatcher,
    HttpDispatcher,
    JsonRPCDispatcher,
    Json2Dispatcher,
    _dispatchers,
)

from .application import (
    Application,
    root,
)

from odoo.modules.registry import Registry

__all__ = [
    "CORS_MAX_AGE",
    "CSRF_TOKEN_MAX_AGE",
    "DEFAULT_ALLOWED_METHODS",
    "DEFAULT_LANG",
    "DEFAULT_MAX_CONTENT_LENGTH",
    "GEOIP_EMPTY_CITY",
    "GEOIP_EMPTY_COUNTRY",
    "MISSING_CSRF_WARNING",
    "NOT_FOUND_NODB",
    "REJECTED_HTTP_METHODS",
    "ROUTING_KEYS",
    "SAFE_HTTP_METHODS",
    "SESSION_DELETION_TIMER",
    "SESSION_LIFETIME",
    "SESSION_ROTATION_EXCLUDED_PATHS",
    "SESSION_ROTATION_INTERVAL",
    "STATIC_CACHE",
    "STATIC_CACHE_LONG",
    "STORED_SESSION_BYTES",
    "Application",
    "Controller",
    "Dispatcher",
    "FasterRule",
    "FilesystemSessionStore",
    "FutureResponse",
    "GeoIP",
    "HTTPRequest",
    "Headers",
    "HttpDispatcher",
    "HttpExtension",
    "Json2Dispatcher",
    "JsonRPCDispatcher",
    "LazyCompiledBuilder",
    "Registry",
    "RegistryError",
    "Request",
    "Response",
    "ResponseCacheControl",
    "ResponseStream",
    "Session",
    "SessionExpiredException",
    "Stream",
    "_Response",
    "_check_and_complete_route_definition",
    "_dispatchers",
    "_generate_routing_rules",
    "_request_stack",
    "borrow_request",
    "content_disposition",
    "cors_same_host",
    "db_filter",
    "db_list",
    "dispatch_rpc",
    "geoip2",
    "get_default_session",
    "get_session_max_inactivity",
    "is_cors_preflight",
    "maxminddb",
    "register_ensure_db_paths",
    "register_routing_parameters",
    "register_session_rotation_excluded_paths",
    "request",
    "rewind_uploaded_files",
    "root",
    "route",
    "rule_routing_kwargs",
    "serialize_exception",
]

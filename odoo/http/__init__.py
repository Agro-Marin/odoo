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
    prepare_default_session,
    is_ensure_db_path,
    register_ensure_db_paths,
    register_session_rotation_excluded_paths,
)

from .exceptions import (
    RegistryError,
    SessionExpiredException,
)

from ._protocols import HttpExtension

from .helpers import (
    content_disposition,
    invalidate_db_list_cache,
    resolve_cors_same_host,
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
    prepare_routing_map,
    FasterRule,
    fragment_to_query_string,
    LazyCompiledBuilder,
    register_routing_parameters,
    route,
    prepare_rule_kwargs,
    _generate_routing_rules,
    _prepare_route_fragment,
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

from .openapi import (
    prepare_openapi_document,
    iter_map_routes,
    prepare_openapi_from_map,
    RouteInfo,
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
    prepare_no_content_response,
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

from . import _retry as _retry

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
    "RouteInfo",
    "Session",
    "SessionExpiredException",
    "Stream",
    "_Response",
    "_dispatchers",
    "_generate_routing_rules",
    "_prepare_route_fragment",
    "_request_stack",
    "borrow_request",
    "content_disposition",
    "db_filter",
    "db_list",
    "dispatch_rpc",
    "fragment_to_query_string",
    "geoip2",
    "get_session_max_inactivity",
    "invalidate_db_list_cache",
    "is_cors_preflight",
    "is_ensure_db_path",
    "iter_map_routes",
    "maxminddb",
    "prepare_default_session",
    "prepare_no_content_response",
    "prepare_openapi_document",
    "prepare_openapi_from_map",
    "prepare_routing_map",
    "prepare_rule_kwargs",
    "register_ensure_db_paths",
    "register_routing_parameters",
    "register_session_rotation_excluded_paths",
    "request",
    "resolve_cors_same_host",
    "rewind_uploaded_files",
    "root",
    "route",
    "serialize_exception",
]

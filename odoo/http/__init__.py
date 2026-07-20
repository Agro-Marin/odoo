r"""\
Odoo HTTP layer / WSGI application

The main duty of this module is to prepare and dispatch all http
requests to their corresponding controllers: from a raw http request
arriving on the WSGI entrypoint to a :class:`~http.Request` arriving at
a module controller with a fully setup ORM available.

Application developers know this module through the
:class:`~odoo.http.Controller` class and the :func:`~odoo.http.route`
decorator, which register methods that deliver web content to matching URLs.

The call graph below shows the processing layers each request passes through
before reaching the ``@route``-decorated endpoint::

    Application.__call__
        if path is like '/<module>/static/<path>':
            Request._serve_static

        elif not request.db:
            Request._serve_nodb
                App.nodb_routing_map.match
                Dispatcher.pre_dispatch
                Dispatcher.dispatch
                    route_wrapper
                        endpoint
                Dispatcher.post_dispatch

        else:
            Request._serve_db
                env['ir.http']._match
                if not match:
                    transaction.retrying(Request._serve_ir_http_fallback)
                        env['ir.http']._serve_fallback
                        env['ir.http']._post_dispatch
                else:
                    transaction.retrying(Request._serve_ir_http)
                        env['ir.http']._authenticate
                        env['ir.http']._pre_dispatch
                        Dispatcher.pre_dispatch
                        Dispatcher.dispatch
                            env['ir.http']._dispatch
                                route_wrapper
                                    endpoint
                        env['ir.http']._post_dispatch

Application.__call__
  WSGI entry point, it sanitizes the request, it wraps it in a werkzeug
  request and itself in an Odoo http request. The Odoo http request is
  exposed at ``http.request`` then it is forwarded to either
  ``_serve_static``, ``_serve_nodb`` or ``_serve_db`` depending on the
  request path and the presence of a database. It is also responsible for
  ensuring any error is properly logged and encapsulated in a HTTP error
  response.

Request._serve_static
  Handle all requests to ``/<module>/static/<asset>`` paths, open the
  underlying file on the filesystem and stream it via
  :meth:`Stream.get_response`

Request._serve_nodb
  Handle requests to ``@route(auth='none')`` endpoints when the user is
  not connected to a database. It performs limited operations, just
  matching the auth='none' endpoint using the request path and then it
  delegates to Dispatcher.

Request._serve_db
  Handle all requests that are not static when it is possible to connect
  to a database. It opens a registry on the database, manage the request
  cursor and environment. The function decides whether to use a
  read-only or a read/write cursor for its operations:
  ``check_signaling``, ``match`` and ``serve_fallback`` are called using
  the same read-only cursor; ``_serve_ir_http`` is called reusing the
  same (but reset) read-only cursor, or a new read/write one.

service.transaction.retrying
  Manage the cursor, the environment and exceptions that occurred while
  executing the underlying function. They recover from various
  exceptions such as serialization errors and writes in read-only
  transactions. They catches all other exceptions and attach a http
  response to them (e.g. 500 - Internal Server Error)

ir.http._match
  Match the controller endpoint that correspond to the request path.
  Beware that there is an important override for portal and website
  inside of the ``http_routing`` module.

ir.http._serve_fallback
  Find alternative ways to serve a request when its path does not match
  any controller. The path could be matching an attachment URL, a blog
  page, etc.

ir.http._authenticate
  Ensure the user on the current environment fulfill the requirement of
  ``@route(auth=...)``. Using the ORM outside of abstract models is
  unsafe prior to calling this function.

ir.http._pre_dispatch/Dispatcher.pre_dispatch
  Prepare the system to handle the current request, often used to save
  some extra query-string parameters in the session (e.g. ?debug=1)

ir.http._dispatch/Dispatcher.dispatch
  Deserialize the HTTP request body into ``request.params`` according to
  @route(type=...), call the controller endpoint, serialize its return
  value into an HTTP Response object.

ir.http._post_dispatch/Dispatcher.post_dispatch
  Post process the response returned by the controller endpoint. Used to
  inject various headers such as Content-Security-Policy.

ir.http._handle_error
  Not present in the call-graph, is called for un-managed exceptions (SE
  or RO) that occurred inside of ``service.transaction.retrying``. It
  returns a http response that wraps the error that occurred.

This package was split from a monolithic http.py for maintainability.
All symbols are re-exported for backward compatibility.
"""

# Constants
from .constants import (
    CORS_MAX_AGE,
    CSRF_TOKEN_MAX_AGE,
    DEFAULT_LANG,
    DEFAULT_MAX_CONTENT_LENGTH,
    GEOIP_EMPTY_CITY,
    GEOIP_EMPTY_COUNTRY,
    MISSING_CSRF_WARNING,
    NOT_FOUND_NODB,
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
    geoip2,
    maxminddb,
)

# Session internals (for tests)
from .session import _session_identifier_re

# Exceptions
from .exceptions import (
    RegistryError,
    SessionExpiredException,
)

# Protocols
from ._protocols import HttpExtension

# Helper functions
from .helpers import (
    content_disposition,
    db_filter,
    db_list,
    dispatch_rpc,
    get_session_max_inactivity,
    is_cors_preflight,
    rewind_uploaded_files,
    serialize_exception,
)

# Stream
from .stream import Stream

# Controller
from .controller import Controller

# Routing
from .routing import (
    route,
    rule_routing_kwargs,
    _generate_routing_rules,
    _check_and_complete_route_definition,
)

# Session
from .session import (
    FilesystemSessionStore,
    Session,
)

# GeoIP
from .geoip import GeoIP

# Core request state
from .core import (
    _request_stack,
    request,
    borrow_request,
)

# HTTP wrappers
from .wrappers import (
    HTTPRequest,
    Response,
    FutureResponse,
    Headers,
    ResponseCacheControl,
    ResponseStream,
    _Response,
)

# Request
from .request_class import Request

# Dispatchers
from .dispatcher import (
    Dispatcher,
    HttpDispatcher,
    JsonRPCDispatcher,
    Json2Dispatcher,
    _dispatchers,
)

# Application
from .application import (
    Application,
    root,
)

# Re-exported for backward compatibility. NOTE: this binding is NOT an effective
# monkeypatch point for the request path. The ONLY ``Registry(self.db)`` call site
# is ``_serve.py`` (``_serve_db`` → ``_acquire_registry_cursor``), which resolves
# ``Registry`` from its OWN namespace, so patching ``odoo.http.Registry`` leaves it
# untouched — a regression from the monolithic ``http.py``, where one namespace
# made this patch point work. Patch ``odoo.http._serve.Registry`` to steer
# dispatch. ``request_class.py`` also imports ``Registry`` but has NO call site
# (annotation-only).
from odoo.modules.registry import Registry

__all__ = [
    # Constants
    "CORS_MAX_AGE",
    "CSRF_TOKEN_MAX_AGE",
    "DEFAULT_LANG",
    "DEFAULT_MAX_CONTENT_LENGTH",
    "GEOIP_EMPTY_CITY",
    "GEOIP_EMPTY_COUNTRY",
    "MISSING_CSRF_WARNING",
    "NOT_FOUND_NODB",
    "ROUTING_KEYS",
    "SAFE_HTTP_METHODS",
    "SESSION_DELETION_TIMER",
    "SESSION_LIFETIME",
    "SESSION_ROTATION_EXCLUDED_PATHS",
    "SESSION_ROTATION_INTERVAL",
    "STATIC_CACHE",
    "STATIC_CACHE_LONG",
    "STORED_SESSION_BYTES",
    # Application
    "Application",
    # Controller
    "Controller",
    # Dispatchers
    "Dispatcher",
    # Session
    "FilesystemSessionStore",
    # Wrappers
    "FutureResponse",
    # GeoIP
    "GeoIP",
    "HTTPRequest",
    "Headers",
    "HttpDispatcher",
    "HttpExtension",
    "Json2Dispatcher",
    "JsonRPCDispatcher",
    # Registry
    "Registry",
    # Exceptions
    "RegistryError",
    # Request
    "Request",
    "Response",
    "ResponseCacheControl",
    "ResponseStream",
    "Session",
    "SessionExpiredException",
    # Stream
    "Stream",
    "_Response",
    # Routing
    "_check_and_complete_route_definition",
    "_dispatchers",
    "_generate_routing_rules",
    # Core
    "_request_stack",
    "borrow_request",
    # Helpers
    "content_disposition",
    "db_filter",
    "db_list",
    "dispatch_rpc",
    "geoip2",
    "get_default_session",
    "get_session_max_inactivity",
    "is_cors_preflight",
    "maxminddb",
    "request",
    "rewind_uploaded_files",
    "root",
    "route",
    "rule_routing_kwargs",
    "serialize_exception",
]

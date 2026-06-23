import functools
import logging
import threading
from collections.abc import Callable, Iterable
from typing import Any
from urllib.parse import urlencode, urlparse

import werkzeug.routing
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix as ProxyFix_
from werkzeug.wrappers import Response

import odoo.tools
from odoo.exceptions import AccessDenied, AccessError, UserError
from odoo.modules import module as module_manager
from odoo.tools import config, file_path
from odoo.tools.misc import real_time

from .constants import (
    ENSURE_DB_PATH_PREFIX,
    ENSURE_DB_PATHS,
    geoip2,
    maxminddb,
)
from .core import _request_stack, request
from .exceptions import RegistryError, SessionExpiredException
from .request_class import Request
from .routing import _generate_routing_rules, rule_routing_kwargs
from .session import FilesystemSessionStore, Session
from .wrappers import HTTPRequest

_logger = logging.getLogger(__name__)

# Cached ProxyFix instance — we only use it for the side effect of
# rewriting environ keys (X-Forwarded-For/Proto/Host), no need to
# instantiate a new middleware on every request.
_proxy_fix = ProxyFix_(
    lambda environ, start_response: [],
    x_for=1,
    x_proto=1,
    x_host=1,
)


def _noop_start_response(status: str, headers: list[tuple[str, str]]) -> None:
    """No-op start_response for ProxyFix."""


_UNSET = object()


class _locked_cached_property(functools.cached_property):
    """Thread-safe :func:`functools.cached_property`.

    ``functools.cached_property`` dropped its internal lock in Python 3.12, so
    under concurrent first-access (a cold worker hit by parallel requests) the
    factory can run more than once. For the singleton :data:`root` that means
    rebuilding the whole ``nodb_routing_map`` redundantly and — worse — opening
    a second GeoIP ``Reader`` whose file handle then leaks. This subclass
    double-checks the instance ``__dict__`` under a per-descriptor lock so the
    factory runs exactly once.

    It deliberately *subclasses* ``functools.cached_property`` rather than
    reimplementing the descriptor, so introspection that special-cases the
    stdlib type keeps working — notably :func:`odoo.tools.reset_cached_properties`,
    which the http test-suite uses to swap in in-memory ``session_store`` /
    GeoIP test doubles. Like its base it stays a non-data descriptor, so once
    the value is cached the instance ``__dict__`` shadows the descriptor and
    the lock is never taken again on the hot read path.
    """

    def __init__(self, func: Callable) -> None:
        super().__init__(func)
        self.lock = threading.Lock()

    def __get__(self, instance: object, owner: type | None = None) -> Any:
        if instance is None:
            return self
        if self.attrname is None:
            # No __set_name__ ran (e.g. attached dynamically); defer to the
            # base implementation, which raises the appropriate TypeError.
            return super().__get__(instance, owner)
        cache = instance.__dict__
        val = cache.get(self.attrname, _UNSET)
        if val is _UNSET:
            with self.lock:
                # Re-read under the lock: a peer may have filled it while we
                # waited, in which case we must not run the factory again.
                val = cache.get(self.attrname, _UNSET)
                if val is _UNSET:
                    val = self.func(instance)
                    cache[self.attrname] = val
        return val


class Application:
    """Odoo WSGI application"""

    # See also: https://www.python.org/dev/peps/pep-3333

    def initialize(self) -> None:
        """
        Initialize the application.

        This is to be called when setting up a WSGI application after
        initializing the configuration values.
        """
        module_manager.initialize_sys_path()
        from odoo.service.server import load_server_wide_modules

        load_server_wide_modules()

    def static_path(self, module_name: str) -> str | None:
        """
        Map module names to their absolute ``static`` path on the file
        system.
        """
        manifest = module_manager.Manifest.for_addon(module_name, display_warning=False)
        return manifest.static_path if manifest is not None else None

    def get_static_file(self, url: str, host: str = "") -> str | None:
        """
        Get the full-path of the file if the url resolves to a local
        static file, otherwise return None.

        Without the second host parameters, ``url`` must be an absolute
        path, others URLs are considered faulty.

        With the second host parameters, ``url`` can also be a full URI
        and the authority found in the URL (if any) is validated against
        the given ``host``.
        """

        netloc, path = urlparse(url)[1:3]
        try:
            # First segment is empty for absolute paths (``/foo/static/bar``);
            # ``split`` raises ``ValueError`` for paths without three ``/``
            # separators (already malformed for our purposes).
            _leading, module, static, resource = path.split("/", 3)
        except ValueError:
            return None

        if netloc and netloc != host:
            return None

        # Hostless URLs of the form ``odoo.com/<addon>/static/<file>`` have
        # no scheme and no ``//``, so ``urlparse`` leaves ``netloc`` empty
        # and stuffs the implicit authority into the first path segment
        # (``_leading``).  Validate that against ``host`` too — otherwise a
        # caller passing ``host=""`` would silently accept any host prefix.
        if not netloc and _leading and _leading != host:
            return None

        if not (static == "static" and resource):
            return None

        static_path = self.static_path(module)
        if not static_path:
            return None

        try:
            return file_path(f"{static_path}/{resource}")
        except FileNotFoundError:
            return None

    @_locked_cached_property
    def nodb_routing_map(self):
        nodb_routing_map = werkzeug.routing.Map(strict_slashes=False, converters=None)
        for url, endpoint in _generate_routing_rules(
            [""] + config["server_wide_modules"], nodb_only=True
        ):
            rule = werkzeug.routing.Rule(
                url, endpoint=endpoint, **rule_routing_kwargs(endpoint)
            )
            rule.merge_slashes = False
            nodb_routing_map.add(rule)

        return nodb_routing_map

    @_locked_cached_property
    def session_store(self):
        path = odoo.tools.config.session_dir
        _logger.debug("HTTP sessions stored in: %s", path)
        return FilesystemSessionStore(path, session_class=Session, renew_missing=True)

    def get_db_router(self, db: str | None) -> werkzeug.routing.Map:
        if not db:
            return self.nodb_routing_map
        return request.env["ir.http"].routing_map()

    @_locked_cached_property
    def geoip_city_db(self):
        """A geoip2 City ``Reader``, or ``None`` when one cannot be opened.

        Returning ``None`` (rather than raising) lets ``_locked_cached_property``
        cache the *failure*: a missing/invalid database — or geoip2 not being
        installed — is opened and logged at most once per worker, instead of
        re-attempting the ``Reader`` open (and re-logging) on every request that
        reaches GeoIP. IP resolution is optional, so the caller
        (:meth:`GeoIP._city_record`) treats ``None`` as "no GeoIP context".
        """
        if geoip2 is None:
            return None
        try:
            return geoip2.database.Reader(config["geoip_city_db"])
        except (OSError, maxminddb.InvalidDatabaseError) as exc:
            # Debug, not info: this fires once and a misconfigured/absent City
            # database is an expected optional-feature state, not an operational
            # error worth a per-worker INFO line.
            _logger.debug(
                "Couldn't load Geoip City file at %s (%s). IP Resolver disabled.",
                config["geoip_city_db"],
                exc,
            )
            return None

    @_locked_cached_property
    def geoip_country_db(self):
        """A geoip2 Country ``Reader``, or ``None`` when one cannot be opened.

        Like :meth:`geoip_city_db`, the ``None`` failure result is cached so the
        ``Reader`` open is attempted once per worker. The caller
        (:meth:`GeoIP._country_record`) recovers from ``None`` by reading the
        City database when available.
        """
        if geoip2 is None:
            return None
        try:
            return geoip2.database.Reader(config["geoip_country_db"])
        except (OSError, maxminddb.InvalidDatabaseError) as exc:
            _logger.debug(
                "Couldn't load Geoip Country file (%s); caller will fall back to Geoip City if available.",
                exc,
            )
            return None

    def set_csp(self, response: Response) -> None:
        headers = response.headers
        headers["X-Content-Type-Options"] = "nosniff"

        if "Content-Security-Policy" in headers:
            return

        if not headers.get("Content-Type", "").startswith("image/"):
            return

        headers["Content-Security-Policy"] = "default-src 'none'"

    def _reset_thread_state(self) -> None:
        """Reset the per-request bookkeeping stored on the reused worker thread.

        Worker threads are pooled, so every field the perf logger / slow-request
        watchdog reads (``query_count``, ``perf_t0``, ``cursor_mode``,
        ``dbname``, ``uid``, ``url`` …) must be reset or cleared here. A request
        that fails before populating one would otherwise report the PREVIOUS
        request's value left on this thread. ``url`` in particular is only set
        once ``_post_init`` has run, so it is cleared rather than zeroed.
        """
        current_thread = threading.current_thread()
        current_thread.query_count = 0
        current_thread.query_time = 0
        current_thread.perf_t0 = real_time()
        current_thread.cursor_mode = None
        if hasattr(current_thread, "dbname"):
            del current_thread.dbname
        if hasattr(current_thread, "uid"):
            del current_thread.uid
        if hasattr(current_thread, "url"):
            del current_thread.url
        current_thread.rpc_model_method = ""

    def _apply_proxy_fix(self, environ: dict[str, object]) -> None:
        """Rewrite ``REMOTE_ADDR`` / scheme / host from trusted ``X-Forwarded-*``.

        Runs only under ``proxy_mode`` and only when at least one trusted
        ``X-Forwarded-*`` header is present. The gate covers For/Proto/Host
        (not just Host): a proxy forwarding only For/Proto — e.g. an AWS ALB —
        would otherwise leave ``REMOTE_ADDR`` and ``wsgi.url_scheme`` wrong,
        breaking ``remote_addr``, GeoIP, device traces and ``request.is_secure``.
        ``ProxyFix`` mutates ``environ`` as a side effect (no real middleware
        chain is invoked); see https://github.com/pallets/werkzeug/pull/2184.
        """
        if odoo.tools.config["proxy_mode"] and (
            environ.get("HTTP_X_FORWARDED_FOR")
            or environ.get("HTTP_X_FORWARDED_PROTO")
            or environ.get("HTTP_X_FORWARDED_HOST")
        ):
            _proxy_fix(environ, _noop_start_response)

    def _recover_from_registry_error(
        self, request: Request, httprequest: HTTPRequest, exc: RegistryError
    ) -> Any:
        """Serve a request db-less after its database/registry became unusable.

        ``_serve_db`` raises :class:`RegistryError` when the database is gone or
        its registry is broken. Drop the db, log the session out, then retry the
        request without a database. For ``ensure_db()``-protected routes, strip
        the ``?db=`` query parameter first so no-db serving does not bounce
        straight back to the same broken database.
        """
        _logger.warning(
            "Database or registry unusable, trying without",
            exc_info=exc.__cause__,
        )
        request.db = None
        request.session.logout()
        if (
            httprequest.path.startswith(ENSURE_DB_PATH_PREFIX)
            or httprequest.path in ENSURE_DB_PATHS
        ):
            # ensure_db() protected routes, remove ?db= from the query string
            args_nodb = request.httprequest.args.copy()
            args_nodb.pop("db", None)
            request.reroute(
                httprequest.path,
                urlencode(list(args_nodb.items(multi=True))),
            )
        return request._serve_nodb()

    def _log_request_exception(self, exc: Exception) -> None:
        """Log ``exc`` at the entrypoint so the traceback starts at ``__call__``.

        The level depends on the kind: framework exceptions carry their own
        ``loglevel``; an ``HTTPException`` is the controller's deliberate status
        choice and is not logged; auth/user errors are warnings; anything else
        is an unexpected 500 logged with a full traceback.
        """
        if hasattr(exc, "loglevel"):
            _logger.log(
                exc.loglevel,
                exc,
                exc_info=getattr(exc, "exc_info", None),
            )
        elif isinstance(exc, HTTPException):
            pass
        elif isinstance(exc, SessionExpiredException):
            _logger.info(exc)
        elif isinstance(exc, AccessError):
            _logger.warning(exc, exc_info="access" in config["dev_mode"])
        elif isinstance(exc, UserError):
            _logger.warning(exc)
        else:
            _logger.exception("Exception during request handling.")

    def _ensure_error_response(self, exc: Exception, request: Request | None) -> None:
        """Guarantee ``exc`` carries a WSGI ``error_response`` handler.

        In the normal path the dispatcher's ``handle_error`` builds it; when the
        request was never constructed (e.g. a bad environ before ``Request`` was
        built) there is no dispatcher, so fall back to a generic 500.
        """
        if hasattr(exc, "error_response"):
            return
        if isinstance(exc, AccessDenied):
            exc.suppress_traceback()
        if request is not None:
            exc.error_response = request.dispatcher.handle_error(exc)
        else:
            from werkzeug.exceptions import InternalServerError

            # ``str(Exception()) == ""``; pass ``None`` (not the empty string)
            # so werkzeug uses its built-in description for the 500 page instead
            # of rendering an empty <p>.
            exc.error_response = InternalServerError(str(exc) or None)

    def __call__(
        self, environ: dict[str, object], start_response: Callable
    ) -> Iterable[bytes]:
        """
        WSGI application entry point.

        :param dict environ: container for CGI environment variables
            such as the request HTTP headers, the source IP address and
            the body as an io file.
        :param callable start_response: function provided by the WSGI
            server that this application must call in order to send the
            HTTP response status line and the response headers.
        """
        self._reset_thread_state()
        self._apply_proxy_fix(environ)

        with HTTPRequest(environ) as httprequest:
            # Build Request and push to the stack *inside* the try so early
            # failures (e.g. bad environ) are converted to an Odoo error
            # response instead of bubbling raw to the WSGI server.
            request: Request | None = None
            pushed = False
            try:
                request = Request(httprequest, app=self)
                _request_stack.push(request)
                pushed = True

                request._post_init()
                threading.current_thread().url = httprequest.url

                static_file = self.get_static_file(httprequest.path)
                if static_file:
                    response = request._serve_static(static_file)
                elif request.db:
                    try:
                        with request._get_profiler_context_manager():
                            response = request._serve_db()
                    except RegistryError as exc:
                        response = self._recover_from_registry_error(
                            request, httprequest, exc
                        )
                else:
                    response = request._serve_nodb()
                return response(environ, start_response)

            except Exception as exc:
                # Log here so the traceback starts with ``__call__``, then make
                # sure the exception carries a WSGI error response to return.
                self._log_request_exception(exc)
                self._ensure_error_response(exc, request)
                return exc.error_response(environ, start_response)

            finally:
                if pushed:
                    _request_stack.pop()


root = Application()

import functools
import logging
import threading
from collections.abc import Callable, Iterable
from pathlib import Path
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
)
from .core import _request_stack, request
from .exceptions import RegistryError, SessionExpiredException
from .geoip import geoip2, maxminddb
from .request_class import Request
from .routing import FasterRule, _generate_routing_rules, rule_routing_kwargs
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


@functools.lru_cache(maxsize=4096)
def _resolve_static_resource(static_path: str, resource: str) -> str:
    """Resolve ``resource`` under a module's validated ``static_path``, cached.

    ``file_path`` costs ~150-300µs (it ``Path.resolve()``s every ``addons_path``
    entry to reject symlink/``..`` escapes) and its url→file mapping is stable for
    a deployment, so cache *positive* resolutions. ``FileNotFoundError`` is not
    cached (``lru_cache`` skips exceptions), so a file added in dev mode is seen
    next request and missing-path probes can't evict useful entries; a later
    *deleted* file still 404s because :meth:`Stream._from_trusted_path` stats it
    per request. Keyed by ``static_path`` so a manifest swap changes the key.

    ``file_path`` only enforces the *addons-tree* boundary, so a ``..`` in
    ``resource`` could escape ``static/`` while staying in the addon, disclosing
    Python source. Re-assert the resolved file is contained in ``static_path``
    (``resolve()`` vs ``resolve()``, so a symlinked ``static/`` isn't defeated),
    matching ``werkzeug.security.safe_join`` on the cold path.
    """
    resolved = file_path(f"{static_path}/{resource}")
    if not Path(resolved).resolve().is_relative_to(Path(static_path).resolve()):
        raise FileNotFoundError(resolved)
    return resolved


class _locked_cached_property(functools.cached_property):
    """Thread-safe :func:`functools.cached_property`.

    Python 3.12 dropped the stdlib lock, so under concurrent first-access (a cold
    worker hit by parallel requests) the factory can run twice — for :data:`root`
    that rebuilds ``nodb_routing_map`` and leaks a second GeoIP ``Reader`` handle.
    This subclass double-checks the instance ``__dict__`` under a per-descriptor
    lock so the factory runs exactly once.

    It *subclasses* (rather than reimplements) so stdlib-type introspection still
    works — notably :func:`odoo.tools.reset_cached_properties`, which the test
    suite uses to swap in test doubles. It stays a non-data descriptor, so once
    cached the ``__dict__`` shadows it and the lock is never taken on the hot read.
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
        Called when setting up a WSGI application, after initializing the
        configuration values.
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

        Without the second host parameter, ``url`` must be an absolute
        path; other URLs are considered faulty.

        With the second host parameter, ``url`` can also be a full URI
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

        # Hostnames are case-insensitive (RFC 4343): compare the URL authority to
        # ``host`` case-folded, else a same-host URL spelled ``Example.com`` misses
        # the local-static fast path and falls through to slower attachment serving.
        host = host.lower()
        if netloc and netloc.lower() != host:
            return None

        # A hostless URL like ``odoo.com/<addon>/static/<file>`` has no ``//``, so
        # ``urlparse`` leaves ``netloc`` empty and puts the authority in the first
        # path segment (``_leading``). Validate that against ``host`` too.
        if not netloc and _leading and _leading.lower() != host:
            return None

        if not (static == "static" and resource):
            return None

        static_path = self.static_path(module)
        if not static_path:
            return None

        try:
            return _resolve_static_resource(static_path, resource)
        except FileNotFoundError:
            return None

    @_locked_cached_property
    def nodb_routing_map(self):
        nodb_routing_map = werkzeug.routing.Map(strict_slashes=False, converters=None)
        for url, endpoint in _generate_routing_rules(
            [""] + config["server_wide_modules"], nodb_only=True
        ):
            # ``FasterRule`` (lazy builder compilation), like the per-database map
            # in ``ir.http.routing_map`` — the nodb map used a plain ``Rule`` and
            # paid full builder-compilation up front for rules that are only
            # matched, never ``url_for``-built.
            rule = FasterRule(url, endpoint=endpoint, **rule_routing_kwargs(endpoint))
            rule.merge_slashes = False
            nodb_routing_map.add(rule)

        return nodb_routing_map

    @_locked_cached_property
    def session_store(self):
        path = odoo.tools.config.session_dir
        _logger.debug("HTTP sessions stored in: %s", path)
        return FilesystemSessionStore(path, session_class=Session, renew_missing=True)

    def get_db_router(self, db: str | None, env: Any = None) -> werkzeug.routing.Map:
        """Return the routing map serving ``db``, or the db-less one.

        A db-backed routing map can only be built from an ``Environment`` (it is
        an ORM-cached model method needing a cursor), so ``db`` alone cannot
        produce one -- it only selects *which* map. Callers that already hold an
        env should pass it: relying on the implicit ``request.env`` makes an
        otherwise pure routing lookup unusable outside an HTTP request, and
        silently ignores the caller's env (user, company, website context).
        """
        if not db:
            return self.nodb_routing_map
        return (env if env is not None else request.env)["ir.http"].routing_map()

    @_locked_cached_property
    def geoip_city_db(self):
        """A geoip2 City ``Reader``, or ``None`` when one cannot be opened.

        Returning ``None`` lets ``_locked_cached_property`` cache the *failure*,
        so a missing/invalid database (or absent geoip2) is opened and logged at
        most once per worker. IP resolution is optional, so the caller
        (:meth:`GeoIP._city_record`) treats ``None`` as "no GeoIP context".
        """
        if geoip2 is None:
            return None
        try:
            return geoip2.database.Reader(config["geoip_city_db"])
        except (OSError, maxminddb.InvalidDatabaseError) as exc:
            # Debug, not info: an absent/misconfigured City db is an expected
            # optional-feature state, logged once per worker.
            _logger.debug(
                "Couldn't load Geoip City file at %s (%s). IP Resolver disabled.",
                config["geoip_city_db"],
                exc,
            )
            return None

    @_locked_cached_property
    def geoip_country_db(self):
        """A geoip2 Country ``Reader``, or ``None`` when one cannot be opened.

        Like :meth:`geoip_city_db`, the ``None`` failure is cached (opened once
        per worker). The caller (:meth:`GeoIP._country_record`) falls back to the
        City database.
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
        """Reset per-request bookkeeping on the pooled worker thread.

        Every field the perf logger / watchdog reads (``query_count``,
        ``perf_t0``, ``cursor_mode``, ``dbname``, ``uid``, ``url`` …) must be reset
        here, else a request failing before populating one reports the PREVIOUS
        request's value. ``url`` is cleared (not zeroed) as it is set only later.
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

        Runs only under ``proxy_mode`` with at least one trusted ``X-Forwarded-*``
        header. The gate covers For/Proto/Host (not just Host): a proxy forwarding
        only For/Proto (e.g. an AWS ALB) would otherwise leave ``REMOTE_ADDR`` /
        scheme wrong, breaking GeoIP, device traces and ``is_secure``. ``ProxyFix``
        mutates ``environ`` as a side effect; see pallets/werkzeug#2184.
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

        Drop the db, log the session out, then retry without a database.

        The logout is made *durable* only when the database's fate could be
        determined (``exc.db_absent`` is ``True`` — dropped — or ``False`` —
        present but with an unusable registry, where a durable logout prevents
        a per-request registry-rebuild storm). When the catalog itself was
        unreachable (``db_absent is None``, e.g. PostgreSQL restarting), the
        outage says nothing about the session: this request is still served
        logged-out and db-less (so ``ensure_db()`` controllers redirect to the
        selector as usual), but the session file is left untouched
        (``can_save = False``) — destroying every active session over a
        transient blip would force a site-wide re-login. For
        ``ensure_db()``-protected routes, strip ``?db=`` first so db-less
        serving does not bounce straight back to the same broken database.
        """
        _logger.warning(
            "Database or registry unusable, trying without",
            exc_info=exc.__cause__,
        )
        request.db = None
        if exc.db_absent is None:
            request.session.can_save = False  # in-memory logout only
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

            # ``str(Exception()) == ""``; pass ``None`` so werkzeug uses its
            # built-in 500 description instead of an empty <p>.
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
            server that this application must call to send the HTTP
            response status line and the response headers.
        """
        self._reset_thread_state()
        self._apply_proxy_fix(environ)

        with HTTPRequest(environ) as httprequest:
            # Build/push inside the try so early failures (e.g. bad environ)
            # become an Odoo error response instead of bubbling raw to WSGI.
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
                # Log here (traceback rooted at ``__call__``), then ensure the
                # exception carries a WSGI error response.
                self._log_request_exception(exc)
                self._ensure_error_response(exc, request)
                return exc.error_response(environ, start_response)

            finally:
                if pushed:
                    _request_stack.pop()


root = Application()

import contextlib
import functools
import logging
import threading
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse

import werkzeug.routing
from werkzeug.exceptions import (
    HTTPException,
    InternalServerError,
    MethodNotAllowed,
    NotFound,
)
from werkzeug.middleware.proxy_fix import ProxyFix as ProxyFix_
from werkzeug.wrappers import Response as WerkzeugResponse

import odoo.tools
from odoo.exceptions import AccessDenied, AccessError, UserError
from odoo.libs.worker_thread import current_worker_thread
from odoo.modules import module as module_manager
from odoo.tools import config, file_path
from odoo.tools.misc import real_time

from .constants import (
    REJECTED_HTTP_METHODS,
    STATIC_ALLOWED_METHODS,
    allow_header,
    is_ensure_db_path,
)
from .core import _request_stack, request
from .exceptions import (
    RegistryError,
    SessionExpiredException,
    get_error_response,
    set_error_response,
)
from .geoip import geoip2, maxminddb
from .request_class import Request
from .routing import _generate_routing_rules, build_routing_map
from .session import FilesystemSessionStore, Session
from .wrappers import HTTPRequest, Response, no_content

_logger = logging.getLogger(__name__)


def _noop_start_response(status: str, headers: list[tuple[str, str]]) -> None:
    pass


@functools.lru_cache(maxsize=4)
def _get_proxy_fix(hops: int) -> ProxyFix_:
    return ProxyFix_(
        lambda environ, start_response: [],
        x_for=hops,
        x_proto=hops,
        x_host=hops,
    )


debugger_attached = False


def _hands_over_to_the_debugger(request: Request | None) -> bool:
    if not debugger_attached:
        return False
    if request is None:
        return True
    return not request.dispatcher.serializes_errors_in_dev_mode


_UNSET = object()


@functools.lru_cache(maxsize=4096)
def _resolve_static_resource(static_path: str, resource: str) -> str:
    resolved = file_path(f"{static_path}/{resource}")
    if not Path(resolved).resolve().is_relative_to(Path(static_path).resolve()):
        raise FileNotFoundError(resolved)
    return resolved


class _locked_cached_property(functools.cached_property):
    def __init__(self, func: Callable) -> None:
        super().__init__(func)
        self.lock = threading.Lock()

    def __get__(self, instance: object, owner: type | None = None) -> Any:
        if instance is None:
            return self
        if self.attrname is None:
            return super().__get__(instance, owner)
        cache = instance.__dict__
        val = cache.get(self.attrname, _UNSET)
        if val is _UNSET:
            with self.lock:
                val = cache.get(self.attrname, _UNSET)
                if val is _UNSET:
                    val = self.func(instance)
                    cache[self.attrname] = val
        return val


class Application:
    def initialize(self) -> None:
        module_manager.initialize_sys_path()
        from odoo.service.server import load_server_wide_modules

        load_server_wide_modules()

    def static_path(self, module_name: str) -> str | None:
        manifest = module_manager.Manifest.for_addon(module_name, display_warning=False)
        return manifest.static_path if manifest is not None else None

    def get_static_file(self, url: str, host: str = "") -> str | None:

        try:
            netloc, path = urlparse(url)[1:3]
        except ValueError:
            return None
        try:
            leading_segment, module, static, resource = path.split("/", 3)
        except ValueError:
            return None

        host = host.lower()
        if netloc and netloc.lower() != host:
            return None

        if not netloc and leading_segment and leading_segment.lower() != host:
            return None

        if not (static == "static" and resource):
            return None

        static_path = self.static_path(module)
        if not static_path:
            return None

        try:
            return _resolve_static_resource(static_path, resource)
        except FileNotFoundError, ValueError:
            return None

    @_locked_cached_property
    def nodb_routing_map(self):
        return build_routing_map(
            _generate_routing_rules(
                [""] + config["server_wide_modules"], nodb_only=True
            )
        )

    @_locked_cached_property
    def session_store(self):
        path = odoo.tools.config.session_dir
        _logger.debug("HTTP sessions stored in: %s", path)
        return FilesystemSessionStore(path, session_class=Session, renew_missing=True)

    def get_db_router(self, db: str | None, env: Any = None) -> werkzeug.routing.Map:
        if not db:
            return self.nodb_routing_map
        router_env = env if env is not None else request.env
        assert router_env is not None, "a database router needs a bound environment"
        return router_env["ir.http"].routing_map()

    @_locked_cached_property
    def geoip_city_db(self):
        if geoip2 is None:
            return None
        try:
            return geoip2.database.Reader(config["geoip_city_db"])
        except (OSError, maxminddb.InvalidDatabaseError) as exc:
            _logger.debug(
                "Couldn't load Geoip City file at %s (%s). IP Resolver disabled.",
                config["geoip_city_db"],
                exc,
            )
            return None

    @_locked_cached_property
    def geoip_country_db(self):
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

    def set_csp(self, response: WerkzeugResponse | Response) -> None:
        headers = response.headers
        if "X-Content-Type-Options" not in headers:
            headers["X-Content-Type-Options"] = "nosniff"

        if "Content-Security-Policy" in headers:
            return

        if not headers.get("Content-Type", "").startswith("image/"):
            return

        headers["Content-Security-Policy"] = "default-src 'none'"

    def _reset_thread_state(self) -> None:
        current_thread = current_worker_thread()
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
        if odoo.tools.config["proxy_mode"] and (
            environ.get("HTTP_X_FORWARDED_FOR")
            or environ.get("HTTP_X_FORWARDED_PROTO")
            or environ.get("HTTP_X_FORWARDED_HOST")
        ):
            hops = max(1, odoo.tools.config["proxy_hops"] or 1)
            _get_proxy_fix(hops)(environ, _noop_start_response)

    def _recover_from_registry_error(
        self, request: Request, httprequest: HTTPRequest, exc: RegistryError
    ) -> Any:
        _logger.warning(
            "Database or registry unusable, trying without",
            exc_info=exc.__cause__,
        )
        request.db = None
        durable = exc.db_absent is True or (
            exc.db_absent is False and not exc.transient
        )
        if not durable:
            request.session.can_save = False
        request.session.logout()
        if is_ensure_db_path(httprequest.path):
            args_nodb = request.httprequest.args.copy()
            args_nodb.pop("db", None)
            request.reroute(
                httprequest.path,
                urlencode(list(args_nodb.items(multi=True))),
            )
        return request._serve_nodb()

    def _serve_static_file(self, request: Request, static_file: str) -> Any:
        method = request.httprequest.method
        if method in STATIC_ALLOWED_METHODS:
            return request._serve_static(static_file)

        allow = allow_header(STATIC_ALLOWED_METHODS)
        if method == "OPTIONS":
            response = no_content(headers=[("Allow", allow)])
            self.set_csp(response)
            return response
        raise MethodNotAllowed(valid_methods=allow.split(", "))

    def _log_request_exception(self, exc: Exception) -> None:
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
            _logger.error("Exception during request handling.", exc_info=exc)

    def _ensure_error_response(self, exc: Exception, request: Request | None) -> Any:
        existing = get_error_response(exc)
        if existing is not None:
            return existing
        if isinstance(exc, AccessDenied):
            exc.suppress_traceback()
        if request is None:
            response: Any = InternalServerError(str(exc) or None)
        else:
            try:
                response = request.dispatcher.handle_error(exc)
            except Exception:
                _logger.exception("The dispatcher could not build an error response")
                response = InternalServerError()
        set_error_response(exc, response)
        return response

    def _finalize_error_response(
        self, exc: Exception, request: Request | None, response: Any
    ) -> Any:
        if request is None or not request._post_init_done or response is None:
            return response
        try:
            if isinstance(response, HTTPException):
                response = response.get_response(request.httprequest.environ)
            request.dispatcher.post_dispatch(response)
            set_error_response(exc, response)
        except Exception:
            _logger.warning(
                "Could not post-process the error response; "
                "CORS/session headers may be missing.",
                exc_info=True,
            )
        return response

    def __call__(
        self, environ: dict[str, object], start_response: Callable
    ) -> Iterable[bytes]:
        self._reset_thread_state()
        self._apply_proxy_fix(environ)

        with HTTPRequest(environ) as httprequest:
            request: Request | None = None
            pushed = False
            try:
                request = Request(httprequest, app=self)
                _request_stack.push(request)
                pushed = True

                request._post_init()
                current_worker_thread().url = httprequest.url

                if httprequest.method in REJECTED_HTTP_METHODS:
                    raise MethodNotAllowed(valid_methods=allow_header().split(", "))

                if "\x00" in httprequest.path:
                    raise NotFound

                static_file = self.get_static_file(httprequest.path)
                if static_file:
                    response = self._serve_static_file(request, static_file)
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
                self._log_request_exception(exc)
                if _hands_over_to_the_debugger(request):
                    raise
                error_response = self._finalize_error_response(
                    exc, request, self._ensure_error_response(exc, request)
                )
                if error_response is None:
                    error_response = InternalServerError(str(exc) or None)
                return error_response(environ, start_response)

            finally:
                if pushed:
                    _request_stack.pop()
                if request is not None and request.httprequest is not httprequest:
                    with contextlib.suppress(Exception):
                        request.httprequest.close()


root = Application()

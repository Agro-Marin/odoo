from __future__ import annotations

import functools
import logging
from typing import Any

import psycopg
import psycopg.errors
from werkzeug.exceptions import (
    HTTPException,
    NotFound,
    RequestEntityTooLarge,
    UnsupportedMediaType,
)

import odoo.api
from odoo.db import PoolError
from odoo.exceptions import AccessDenied
from odoo.libs.worker_thread import current_worker_thread
from odoo.modules.registry import Registry
from odoo.service.transaction import retrying

from ._protocols import RequestState, ir_http
from ._retry import RequestRetryParticipant
from .constants import NOT_FOUND_NODB, NOT_FOUND_NODB_TEXT, STATIC_CACHE
from .core import borrow_request
from .dispatcher import _dispatchers, get_dispatcher_for_unmatched_route
from .exceptions import RegistryError, get_error_response, set_error_response
from .helpers import is_cors_preflight, rewind_uploaded_files
from .settings import current as current_settings
from .stream import Stream
from .wrappers import Response

_logger = logging.getLogger(__name__)

_PROMOTE = object()
"""What `_serve_readonly` answers when the handler must be replayed read/write."""


class _RequestServeMixin(RequestState):
    def _update_dispatcher(self, rule: Any) -> None:
        routing = rule.endpoint.routing
        dispatcher_cls = _dispatchers[routing["type"]]
        if not is_cors_preflight(
            self, rule.endpoint
        ) and not dispatcher_cls.is_compatible_with_request(self):
            compatible_dispatchers = [
                disp.routing_type
                for disp in _dispatchers.values()
                if disp.is_compatible_with_request(self)
            ]
            e = (
                f"Request inferred type is compatible with {compatible_dispatchers} "
                f"but {routing['routes'][0]!r} is type={routing['type']!r}.\n\n"
                "Please verify the Content-Type request header and try again."
            )
            res = UnsupportedMediaType(e).get_response()
            res.headers["Accept"] = ", ".join(dispatcher_cls.mimetypes)
            raise UnsupportedMediaType(response=res)
        self.dispatcher = dispatcher_cls(self)

    def _serve_static(self, filepath: str) -> Response:
        root = self.app

        try:
            stream = Stream._from_trusted_path(filepath, public=True)
            debug = "assets" in self.session.debug
            res = stream.get_response(
                max_age=0 if debug else STATIC_CACHE,
                content_security_policy=None,
            )
            root.update_security_headers(res)
            return res
        except OSError:
            module, _, path = self.httprequest.path[1:].partition("/static/")
            raise NotFound(f'File "{path}" not found in module {module}.\n') from None

    def _serve_aborted(self, exc: HTTPException) -> Response:
        if exc.response is not None:
            response = exc.get_response()
        else:
            _logger.error(
                "Aborted with a status-less HTTPException while serving %s",
                self.httprequest.path,
                exc_info=exc,
            )
            response = self._prepare_dispatcher_error_response(exc)
        self.dispatcher.post_dispatch(response)
        return response

    def _prepare_dispatcher_error_response(self, exc: HTTPException) -> Response:
        handled = self.dispatcher.prepare_error_response(exc)
        if isinstance(handled, HTTPException):
            return handled.get_response()
        return handled

    def _serve_nodb(self) -> Response:
        root = self.app

        try:
            router = root.nodb_routing_map.bind_to_environ(self.httprequest.environ)
            try:
                rule, args = router.match(return_rule=True)
            except NotFound as exc:
                self.dispatcher = get_dispatcher_for_unmatched_route(self)(self)
                set_error_response(exc, self._prepare_nodb_not_found_response(exc))
                raise
            self._update_dispatcher(rule)
            self.dispatcher.pre_dispatch(rule, args)
            response = self.dispatcher.dispatch(rule.endpoint, args)
            self.dispatcher.post_dispatch(response)
            return response
        except HTTPException as exc:
            if exc.code is not None:
                raise
            return self._serve_aborted(exc)

    def _prepare_nodb_not_found_response(self, exc: NotFound) -> Response:
        if self.dispatcher.routing_type == "http":
            return Response(
                NOT_FOUND_NODB,
                status=exc.code,
                headers=[("Content-Type", "text/html; charset=utf-8")],
            )
        exc.description = NOT_FOUND_NODB_TEXT
        return self._prepare_dispatcher_error_response(exc)

    def _acquire_registry_cursor(self) -> Any:
        db = self.db
        if not db:
            raise RuntimeError("a database-bound request needs a database name")
        cr = None
        try:
            with borrow_request():
                registry = Registry(db)
            cr = registry.cursor(readonly=True)
            self.registry = registry.check_signaling(cr)
            return cr
        except (
            PoolError,
            psycopg.OperationalError,
            psycopg.ProgrammingError,
        ) as e:
            db_absent = None
            try:
                from odoo.db import close_db
                from odoo.service.db import list_dbs

                db_absent = db not in list_dbs(force=True)
                if db_absent:
                    Registry.forget(db)
                    close_db(db)
            except Exception:
                _logger.debug(
                    "Stale-registry cleanup after RegistryError failed",
                    exc_info=True,
                )
            finally:
                if cr is not None:
                    cr.close()
            err = RegistryError(f"Cannot get registry {db}")
            err.db_absent = db_absent
            err.transient = not isinstance(e, psycopg.ProgrammingError)
            raise err from e
        except BaseException:
            if cr is not None:
                cr.close()
            raise

    def _select_serve_target_and_mode(self, registry: Registry) -> tuple[Any, bool]:
        try:
            rule, args = ir_http(registry)._match(self.httprequest.path)
        except NotFound as not_found_exc:
            self.dispatcher = get_dispatcher_for_unmatched_route(self)(self)
            return functools.partial(self._serve_ir_http_fallback, not_found_exc), True

        self._update_dispatcher(rule)
        readonly = rule.endpoint.routing["readonly"]
        if callable(readonly):
            readonly = readonly(rule.endpoint.func.__self__, rule, args)
        return functools.partial(self._serve_ir_http, rule, args), bool(readonly)

    def _serve_readwrite(
        self, serve_func: Any, participant: RequestRetryParticipant
    ) -> Response:
        env = self.env
        if env is None:
            raise RuntimeError("a database-bound request has an environment")
        try:
            return retrying(serve_func, env=env, participant=participant)
        except Exception as exc:
            self._update_served_exception(exc)
            raise

    def _serve_readonly(
        self, serve_func: Any, participant: RequestRetryParticipant
    ) -> Any:
        current_worker_thread().cursor_mode = "ro"
        env = self.env
        if env is None:
            raise RuntimeError("a database-bound request has an environment")
        try:
            return retrying(serve_func, env=env, participant=participant)
        except psycopg.errors.ReadOnlySqlTransaction as exc:
            _logger.warning(
                "%s, retrying with a read/write cursor — readonly route "
                "%s %s attempted a write, so its handler runs a second "
                "time; keep non-transactional side effects (emails, "
                "outbound calls, token burns) out until the first write",
                exc.args[0].rstrip(),
                self.httprequest.method,
                self.httprequest.path,
                exc_info=True,
            )
            current_worker_thread().cursor_mode = "ro->rw"
            participant.on_rollback(exc)
            rewind_uploaded_files(self.httprequest, cause=exc)
            return _PROMOTE
        except Exception as exc:
            self._update_served_exception(exc)
            raise

    def _open_read_write_cursor(self, cr: Any) -> Any:
        env = self.env
        if env is None:
            raise RuntimeError("a database-bound request has an environment")
        if cr.readonly:
            cr.close()
            cr = env.registry.cursor()
        else:
            cr.rollback()
        if cr.readonly:
            e = (
                f"{self.httprequest.method} {self.httprequest.path} needs a "
                f"read/write cursor and the registry handed back a read-only "
                f"one; refusing to run the handler against it."
            )
            raise RuntimeError(e)
        return cr

    def _serve_db(self) -> Response:
        cr: Any = None
        try:
            cr = self._acquire_registry_cursor()
            registry = self.registry
            if registry is None:
                raise RuntimeError("ir.http is only reachable with a registry")
            current_worker_thread().dbname = registry.db_name

            self.env = odoo.api.Environment(
                cr, self.session.uid, self.session.context or {}
            )
            serve_func, readonly = self._select_serve_target_and_mode(registry)
            participant = RequestRetryParticipant(self)

            promoted = False
            if readonly and cr.readonly:
                served = self._serve_readonly(serve_func, participant)
                if served is not _PROMOTE:
                    return served
                promoted = True
            else:
                current_worker_thread().cursor_mode = "rw"

            env = self.env
            if env is None:
                raise RuntimeError("a database-bound request has an environment")
            cr = self._open_read_write_cursor(cr)
            if promoted:
                self._reset_for_replay(cr)
            else:
                self.env = env(cr=cr)
            return self._serve_readwrite(serve_func, participant)
        except HTTPException as exc:
            if exc.code is not None:
                raise
            return self._serve_aborted(exc)
        finally:
            self.env = None
            if cr is not None:
                cr.close()

    def _update_served_exception(self, exc: Exception) -> None:
        if isinstance(exc, HTTPException) and exc.code is None:
            return
        if (
            "werkzeug" in current_settings().dev_mode
            and not self.dispatcher.serializes_errors_in_dev_mode
        ):
            return
        if get_error_response(exc) is None:
            if isinstance(exc, AccessDenied):
                exc.suppress_traceback()
            registry = self._get_bound_registry()
            set_error_response(exc, ir_http(registry)._handle_error(exc))

    def _get_bound_registry(self) -> Registry:
        registry = self.registry
        if registry is None:
            raise RuntimeError("ir.http is only reachable with a registry")
        return registry

    def _check_body_size(self) -> None:
        limit = self.httprequest.max_content_length
        length = self.httprequest.content_length
        if limit is not None and length is not None and length > limit:
            raise RequestEntityTooLarge

    def _serve_ir_http_fallback(self, not_found: NotFound) -> Response:
        registry = self._get_bound_registry()
        ir_http(registry)._apply_max_upload_size()
        self._check_body_size()
        self._params_source = self.get_http_params
        ir_http(registry)._auth_method_public()
        response = ir_http(registry)._serve_fallback()
        if response:
            ir_http(registry)._post_dispatch(response)
            return response

        no_fallback = NotFound()
        no_fallback.__context__ = not_found
        set_error_response(no_fallback, ir_http(registry)._handle_error(no_fallback))
        raise no_fallback

    def _serve_ir_http(self, rule: Any, args: dict[str, Any]) -> Response:
        registry = self._get_bound_registry()
        ir_http(registry)._authenticate(rule.endpoint)
        ir_http(registry)._pre_dispatch(rule, args)
        response = self.dispatcher.dispatch(rule.endpoint, args)
        ir_http(registry)._post_dispatch(response)
        return response

from __future__ import annotations

import functools
import logging
from typing import Any

import psycopg
import psycopg.errors
import werkzeug.security
from werkzeug.exceptions import (
    HTTPException,
    InternalServerError,
    NotFound,
    UnsupportedMediaType,
)

import odoo.api
from odoo.db import PoolError
from odoo.exceptions import AccessDenied
from odoo.libs.worker_thread import current_worker_thread
from odoo.modules.registry import Registry
from odoo.service.transaction import retrying
from odoo.tools import config

from ._protocols import RequestState
from .constants import NOT_FOUND_NODB, STATIC_CACHE
from .dispatcher import (
    HttpDispatcher,
    _dispatchers,
    infer_dispatcher_for_unmatched,
)
from .exceptions import RegistryError
from .helpers import is_cors_preflight, rewind_uploaded_files
from .stream import Stream
from .wrappers import Response

_logger = logging.getLogger(__name__)


class _RequestServeMixin(RequestState):
    def _set_request_dispatcher(self, rule: Any) -> None:
        routing = rule.endpoint.routing
        dispatcher_cls = _dispatchers[routing["type"]]
        if not is_cors_preflight(
            self, rule.endpoint
        ) and not dispatcher_cls.is_compatible_with(self):
            compatible_dispatchers = [
                disp.routing_type
                for disp in _dispatchers.values()
                if disp.is_compatible_with(self)
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

    def _serve_static(self, filepath: str | None = None) -> Response:
        root = self.app

        try:
            if filepath is None:
                module, _, path = self.httprequest.path[1:].partition("/static/")
                directory = root.static_path(module)
                if not directory:
                    raise NotFound(f'Module "{module}" not found.\n')
                filepath = werkzeug.security.safe_join(directory, path)
                if filepath is None:
                    raise NotFound(f'File "{path}" not found in module {module}.\n')
                stream = Stream.from_path(filepath, public=True)
            else:
                stream = Stream._from_trusted_path(filepath, public=True)
            debug = "assets" in self.session.debug
            res = stream.get_response(
                max_age=0 if debug else STATIC_CACHE,
                content_security_policy=None,
            )
            root.set_csp(res)
            return res
        except OSError:
            module, _, path = self.httprequest.path[1:].partition("/static/")
            raise NotFound(f'File "{path}" not found in module {module}.\n') from None

    def _serve_aborted(self, exc: HTTPException) -> Response:
        if exc.response is None and exc.code is None:
            _logger.error(
                "Aborted with a status-less HTTPException while serving %s",
                self.httprequest.path,
                exc_info=exc,
            )
            exc = InternalServerError(exc.description)
        response = exc.get_response()
        HttpDispatcher(self).post_dispatch(response)
        return response

    def _serve_nodb(self) -> Response:
        root = self.app

        try:
            router = root.nodb_routing_map.bind_to_environ(self.httprequest.environ)
            try:
                rule, args = router.match(return_rule=True)
            except NotFound as exc:
                exc.response = Response(
                    NOT_FOUND_NODB,
                    status=exc.code,
                    headers=[
                        ("Content-Type", "text/html; charset=utf-8"),
                    ],
                )
                raise
            self._set_request_dispatcher(rule)
            self.dispatcher.pre_dispatch(rule, args)
            response = self.dispatcher.dispatch(rule.endpoint, args)
            self.dispatcher.post_dispatch(response)
            return response
        except HTTPException as exc:
            if exc.code is not None:
                raise
            return self._serve_aborted(exc)

    def _acquire_registry_cursor(self) -> Any:
        cr = None
        try:
            registry = Registry(self.db)
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

                db_absent = self.db not in list_dbs(force=True)
                if db_absent:
                    Registry.forget(self.db)
                    close_db(self.db)
            except Exception:
                _logger.debug(
                    "Stale-registry cleanup after RegistryError failed",
                    exc_info=True,
                )
            finally:
                if cr is not None:
                    cr.close()
            err = RegistryError(f"Cannot get registry {self.db}")
            err.db_absent = db_absent
            err.transient = not isinstance(e, psycopg.ProgrammingError)
            raise err from e
        except BaseException:
            if cr is not None:
                cr.close()
            raise

    def _serve_db(self) -> Response:
        cr = None
        try:
            cr = self._acquire_registry_cursor()
            current_worker_thread().dbname = self.registry.db_name

            self.env = odoo.api.Environment(cr, self.session.uid, self.session.context)
            try:
                rule, args = self.registry["ir.http"]._match(self.httprequest.path)
            except NotFound as not_found_exc:
                self.dispatcher = infer_dispatcher_for_unmatched(self)(self)
                serve_func = functools.partial(
                    self._serve_ir_http_fallback, not_found_exc
                )
                readonly = True
            else:
                self._set_request_dispatcher(rule)
                serve_func = functools.partial(self._serve_ir_http, rule, args)
                readonly = rule.endpoint.routing["readonly"]
                if callable(readonly):
                    readonly = readonly(rule.endpoint.func.__self__, rule, args)

            promoted = False

            if readonly and cr.readonly:
                current_worker_thread().cursor_mode = "ro"
                try:
                    return retrying(serve_func, env=self.env)
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
                    self._rewind_input_files(exc)
                    self.session = self._get_session_and_dbname(
                        sid=getattr(self.session, "sid", None)
                    )[0]
                    promoted = True
                except Exception as exc:
                    self._update_served_exception(exc)
                    raise
            else:
                current_worker_thread().cursor_mode = "rw"

            if cr.readonly:
                cr.close()
                cr = self.env.registry.cursor()
            else:
                cr.rollback()
            assert not cr.readonly
            if promoted:
                self._reset_for_replay(cr)
            else:
                self.env = self.env(cr=cr)
            try:
                return retrying(serve_func, env=self.env)
            except Exception as exc:
                self._update_served_exception(exc)
                raise
        except HTTPException as exc:
            if exc.code is not None:
                raise
            return self._serve_aborted(exc)
        finally:
            self.env = None
            if cr is not None:
                cr.close()

    def _rewind_input_files(self, cause: Exception | None = None) -> None:
        rewind_uploaded_files(self.httprequest, cause=cause)

    def _update_served_exception(self, exc: Exception) -> None:
        if isinstance(exc, HTTPException) and exc.code is None:
            return
        if (
            "werkzeug" in config["dev_mode"]
            and not self.dispatcher.serializes_errors_in_dev_mode
        ):
            return
        if not hasattr(exc, "error_response"):
            if isinstance(exc, AccessDenied):
                exc.suppress_traceback()
            exc.error_response = self.registry["ir.http"]._handle_error(exc)

    def _serve_ir_http_fallback(self, not_found: NotFound) -> Response:
        self.registry["ir.http"]._apply_max_upload_size()
        self.params = self.get_http_params()
        self.registry["ir.http"]._auth_method_public()
        response = self.registry["ir.http"]._serve_fallback()
        if response:
            self.registry["ir.http"]._post_dispatch(response)
            return response

        no_fallback = NotFound()
        no_fallback.__context__ = not_found
        no_fallback.error_response = self.registry["ir.http"]._handle_error(no_fallback)
        raise no_fallback

    def _serve_ir_http(self, rule: Any, args: dict[str, Any]) -> Response:
        self.registry["ir.http"]._authenticate(rule.endpoint)
        self.registry["ir.http"]._pre_dispatch(rule, args)
        response = self.dispatcher.dispatch(rule.endpoint, args)
        self.registry["ir.http"]._post_dispatch(response)
        return response

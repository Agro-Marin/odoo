"""Routing methods for :class:`~odoo.http.Request`.

This mixin holds the request-routing logic — `_serve_static`, `_serve_db`,
`_serve_nodb` and their helpers — split out of ``request_class.py`` for
file-size hygiene. The methods rely on attributes set in
``Request.__init__`` (``httprequest``, ``session``, ``db``, ``env``,
``registry``, ``dispatcher``, ``params``); they are not standalone.
"""

from __future__ import annotations

import functools
import logging
from typing import Any

import psycopg
import psycopg.errors
import werkzeug.security
from werkzeug.exceptions import HTTPException, NotFound, UnsupportedMediaType

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
    JsonRPCDispatcher,
    _dispatchers,
    infer_dispatcher_for_unmatched,
)
from .exceptions import RegistryError
from .helpers import is_cors_preflight, rewind_uploaded_files
from .stream import Stream
from .wrappers import Response

_logger = logging.getLogger(__name__)


class _RequestServeMixin(RequestState):
    """Routing methods mixed into :class:`~odoo.http.Request` (see module docstring).

    No state of its own; the ``Request`` state it reads and writes is declared by
    :class:`~odoo.http._protocols.RequestState`.
    """

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
        """Serve a static file from the file system.

        ``filepath`` is the absolute, pre-validated path resolved by
        :meth:`Application.get_static_file` at the WSGI static gate. When supplied
        (the hot path) it is trusted and streamed directly, skipping a redundant
        manifest lookup + ``safe_join`` + ``file_path`` resolution; when omitted
        (a direct call) the path is resolved from the request.
        """
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
        """Recover the Response carried by a code-less ``HTTPException``.

        ``abort(Response(...))`` raises an ``HTTPException`` with ``code is None``
        carrying a ready-made Response (CORS 204 preflight, ``Invalid JSON`` 400,
        ...). Run ``post_dispatch`` so CORS / CSP / session-save headers land on
        it, then return it. Shared by :meth:`_serve_nodb` and :meth:`_serve_db`.
        """
        response = exc.get_response()
        HttpDispatcher(self).post_dispatch(response)
        return response

    def _serve_nodb(self) -> Response:
        """
        Dispatch the request to its matching controller in a
        database-free environment.
        """
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
        """Open the database registry and return its initial read-only cursor."""
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
                    Registry.delete(self.db)
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
            # Any error the typed handler above did not expect — an
            # InternalError/DataError from check_signaling, a bug in a
            # signaling override, a KeyboardInterrupt — must still not leak the
            # read-only cursor: _serve_db's own ``finally`` cannot close it,
            # because its local ``cr`` was never assigned (this call raised
            # instead of returning). Close and re-raise unchanged.
            if cr is not None:
                cr.close()
            raise

    def _serve_db(self) -> Response:
        """Load the ORM and use it to process the request."""
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
                    # By the session's current sid, not the cookie's: the first
                    # attempt may have rotated it (see _get_session_and_dbname).
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
        """Rewind uploaded files before re-dispatching on the RO→RW cursor swap.

        Thin wrapper over :func:`~odoo.http.helpers.rewind_uploaded_files`, the
        single rewind primitive shared with the serialization-retry path in
        :func:`~odoo.service.transaction.retrying`, so the two cannot drift.
        ``cause`` is chained onto the raised error.
        """
        rewind_uploaded_files(self.httprequest, cause=cause)

    def _update_served_exception(self, exc: Exception) -> None:
        """Attach an ``error_response`` to ``exc`` in place (side effect only).

        Callers re-raise with a bare ``raise`` to preserve the traceback, so this
        returns nothing. Two cases are left untouched to bubble up:

        * the abort+Response path (``HTTPException``, ``code is None``), recovered
          by :meth:`_serve_db`;
        * ``--dev werkzeug`` on non-JSON routes — skip the styled
          ``ir.http._handle_error`` page so :meth:`Application.__call__` logs the
          traceback and builds a plain response (this fork has no interactive
          debugger, so ``__call__`` is the handler of last resort).
        """
        if isinstance(exc, HTTPException) and exc.code is None:
            return
        if (
            "werkzeug" in config["dev_mode"]
            and self.dispatcher.routing_type != JsonRPCDispatcher.routing_type
        ):
            return
        if not hasattr(exc, "error_response"):
            if isinstance(exc, AccessDenied):
                exc.suppress_traceback()
            exc.error_response = self.registry["ir.http"]._handle_error(exc)

    def _serve_ir_http_fallback(self, not_found: NotFound) -> Response:
        """Serve the request when no controller matched its path.

        Delegate to ``ir.http._serve_fallback`` so modules can serve the request
        another way. If none does, raise a 404 Not Found carrying the rendered
        error page.
        """
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
        """Serve the request via ``ir.http`` when a controller matched its path."""
        self.registry["ir.http"]._authenticate(rule.endpoint)
        self.registry["ir.http"]._pre_dispatch(rule, args)
        response = self.dispatcher.dispatch(rule.endpoint, args)
        self.registry["ir.http"]._post_dispatch(response)
        return response

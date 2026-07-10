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
import threading
from typing import Any

import psycopg
import psycopg.errors
import werkzeug.security
from werkzeug.exceptions import HTTPException, NotFound, UnsupportedMediaType

import odoo.api
from odoo.exceptions import AccessDenied
from odoo.modules.registry import Registry
from odoo.service.transaction import retrying
from odoo.tools import config

from .constants import NOT_FOUND_NODB, STATIC_CACHE
from .dispatcher import HttpDispatcher, JsonRPCDispatcher, _dispatchers
from .exceptions import RegistryError
from .helpers import is_cors_preflight, rewind_uploaded_files
from .stream import Stream
from .wrappers import Response

_logger = logging.getLogger(__name__)


class _RequestServeMixin:
    """Routing methods mixed into :class:`~odoo.http.Request` (see module docstring).

    No state of its own; reads/writes attributes Request initializes
    (``httprequest``, ``session``, ``db``, ``env``, ``registry``, ``dispatcher``,
    ``params``, ``future_response``).
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
            # werkzeug doesn't let us add headers to UnsupportedMediaType
            # so use the following (ugly) to still achieve what we want
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
                # Cold path: resolve module/resource from the request path. The
                # trusted-path branch (hot path) skips this parsing entirely.
                module, _, path = self.httprequest.path[1:].partition("/static/")
                directory = root.static_path(module)
                if not directory:
                    raise NotFound(f'Module "{module}" not found.\n')
                filepath = werkzeug.security.safe_join(directory, path)
                if filepath is None:
                    # ``safe_join`` returns None for traversal/absolute paths;
                    # treat as missing (404) rather than 500.
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
        except OSError:  # cover both missing file and invalid permissions
            # Cold error path only: recompute module/resource for the 404 message.
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
            # Valid response returned via werkzeug.exceptions.abort
            return self._serve_aborted(exc)

    def _acquire_registry_cursor(self) -> Any:
        """Open the database registry and return its initial read-only cursor.

        Sets :attr:`registry` and returns the open RO cursor. **Ownership
        transfers to the caller only on a clean return** — :meth:`_serve_db`'s
        ``finally`` then closes it. On failure this method closes the cursor
        itself and raises :class:`RegistryError`, which :meth:`Application.__call__`
        recovers from by serving db-less. A naive ``return cr`` would leak the
        connection on that failure path — keep the close-on-failure contract. The
        ``database_breaking`` suite in ``test_registry.py`` guards the recovery
        (OperationalError → db gone; ProgrammingError → broken schema).

        AttributeError is a broad, *legacy* arm (no dedicated test): it guards a
        registry observed mid-``Registry.new`` (inserted into ``registries``
        before ``setup_signaling`` runs), but can also mask a real bug in this
        path — re-run that suite before narrowing it.
        """
        cr = None
        try:
            registry = Registry(self.db)
            cr = registry.cursor(readonly=True)
            self.registry = registry.check_signaling(cr)
            return cr
        except (
            AttributeError,
            psycopg.OperationalError,
            psycopg.ProgrammingError,
        ) as e:
            try:
                # If DB no longer exists, clean up stale registry to prevent
                # repeated 30s hangs on subsequent requests.
                from odoo.db import close_db
                from odoo.service.db import list_dbs

                if self.db not in list_dbs(force=True):
                    Registry.delete(self.db)
                    close_db(self.db)
            except Exception:
                _logger.debug(
                    "Stale-registry cleanup after RegistryError failed",
                    exc_info=True,
                )
            finally:
                # Ours until the clean ``return`` above; close it so a failure
                # between cursor-open and that return cannot leak the connection.
                if cr is not None:
                    cr.close()
            raise RegistryError(f"Cannot get registry {self.db}") from e

    def _serve_db(self) -> Response:
        """Load the ORM and use it to process the request."""
        # reuse the same cursor for building, checking the registry, for
        # matching the controller endpoint and serving the data
        cr = None
        try:
            # Open the registry + initial RO cursor. RegistryError (broken/absent
            # db) propagates to Application.__call__, which retries db-less.
            cr = self._acquire_registry_cursor()
            threading.current_thread().dbname = self.registry.db_name

            # find the controller endpoint to use
            self.env = odoo.api.Environment(cr, self.session.uid, self.session.context)
            try:
                rule, args = self.registry["ir.http"]._match(self.httprequest.path)
            except NotFound as not_found_exc:
                # no controller endpoint matched -> fallback or 404
                serve_func = functools.partial(
                    self._serve_ir_http_fallback, not_found_exc
                )
                readonly = True
            else:
                # a controller endpoint matched -> dispatch the request
                self._set_request_dispatcher(rule)
                serve_func = functools.partial(self._serve_ir_http, rule, args)
                readonly = rule.endpoint.routing["readonly"]
                if callable(readonly):
                    readonly = readonly(rule.endpoint.func.__self__, rule, args)

            # keep on using the RO cursor when a readonly route matched,
            # and for serve fallback
            if readonly and cr.readonly:
                threading.current_thread().cursor_mode = "ro"
                try:
                    return retrying(serve_func, env=self.env)
                except psycopg.errors.ReadOnlySqlTransaction as exc:
                    # A read-only-marked controller attempted a write. Do NOT
                    # raise: fall through to the ``if cr.readonly:`` swap below,
                    # which retries on a read/write cursor. Adding an
                    # ``else``/``return`` here would silently disable that retry.
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
                    threading.current_thread().cursor_mode = "ro->rw"
                    # The RO attempt already consumed uploaded file streams (now
                    # at EOF); rewind them so the RW retry re-reads the body
                    # instead of an empty upload (as ``retrying`` does).
                    self._rewind_input_files(exc)
                    # The aborted RO attempt may have mutated the in-memory
                    # session (e.g. a handler that set session.uid/context before
                    # its first write); re-fetch it so the RW replay starts from
                    # persisted state, matching retrying()'s per-attempt refresh.
                    self.session = self._get_session_and_dbname()[0]
                except Exception as exc:
                    # ``_update_served_exception`` attaches ``error_response`` to
                    # ``exc``; the bare ``raise`` preserves the original traceback.
                    self._update_served_exception(exc)
                    raise
            else:
                threading.current_thread().cursor_mode = "rw"

            # we must use a RW cursor when a read/write route matched, or
            # there was a ReadOnlySqlTransaction error
            if cr.readonly:
                cr.close()
                cr = self.env.registry.cursor()
            else:
                # already a RW cursor; start a new transaction to avoid
                # repeatable-read serialization errors (``retrying`` skips
                # check_signaling and would just succeed the second time).
                cr.rollback()
            assert not cr.readonly
            self.env = self.env(cr=cr)
            try:
                return retrying(serve_func, env=self.env)
            except Exception as exc:
                self._update_served_exception(exc)
                raise
        except HTTPException as exc:
            if exc.code is not None:
                raise
            # Valid response returned via werkzeug.exceptions.abort
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
            return  # bubble up to _serve_db
        if (
            "werkzeug" in config["dev_mode"]
            and self.dispatcher.routing_type != JsonRPCDispatcher.routing_type
        ):
            return  # bubble up to Application.__call__'s error handler
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
        self.params = self.get_http_params()
        self.registry["ir.http"]._auth_method_public()
        response = self.registry["ir.http"]._serve_fallback()
        if response:
            self.registry["ir.http"]._post_dispatch(response)
            return response

        no_fallback = NotFound()
        no_fallback.__context__ = (
            not_found  # During handling of {not_found}, {no_fallback} occurred:
        )
        no_fallback.error_response = self.registry["ir.http"]._handle_error(no_fallback)
        raise no_fallback

    def _serve_ir_http(self, rule: Any, args: dict[str, Any]) -> Response:
        """Serve the request via ``ir.http`` when a controller matched its path."""
        self.registry["ir.http"]._authenticate(rule.endpoint)
        self.registry["ir.http"]._pre_dispatch(rule, args)
        response = self.dispatcher.dispatch(rule.endpoint, args)
        self.registry["ir.http"]._post_dispatch(response)
        return response

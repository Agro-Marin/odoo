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
from .exceptions import RegistryError
from .helpers import is_cors_preflight
from .stream import Stream
from .wrappers import Response

_logger = logging.getLogger(__name__)


class _RequestServeMixin:
    """Routing methods for :class:`~odoo.http.Request`.

    Mixed into Request via inheritance. The mixin has no state of its own;
    it reads/writes attributes that Request initializes:
    ``httprequest``, ``session``, ``db``, ``env``, ``registry``,
    ``dispatcher``, ``params``, ``future_response``.
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

        ``filepath`` is the absolute, already-validated path that
        :meth:`Application.get_static_file` resolved at the WSGI entrypoint's
        static gate. When supplied (the hot path) it is trusted and streamed
        directly, avoiding a second redundant resolution — manifest lookup +
        ``safe_join`` + ``file_path`` validation — on every static hit. When
        omitted (a direct call), the path is resolved from the request as
        before.
        """
        root = self.app

        module, _, path = self.httprequest.path[1:].partition("/static/")
        try:
            if filepath is None:
                directory = root.static_path(module)
                if not directory:
                    raise NotFound(f'Module "{module}" not found.\n')
                filepath = werkzeug.security.safe_join(directory, path)
                if filepath is None:
                    # ``safe_join`` returns None for traversal/absolute paths;
                    # treat as a missing file rather than letting the None flow
                    # into ``file_path`` and raise a non-OSError (500).
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
            raise NotFound(f'File "{path}" not found in module {module}.\n') from None

    def _serve_aborted(self, exc: HTTPException) -> Response:
        """Recover the Response carried by a code-less ``HTTPException``.

        ``werkzeug.exceptions.abort(Response(...))`` raises an ``HTTPException``
        whose ``code is None`` but which carries a ready-made Response (the CORS
        204 preflight in ``Dispatcher.pre_dispatch``, the ``Invalid JSON`` 400
        in the JSON dispatchers, ...). Run ``post_dispatch`` so the CORS / CSP /
        session-save headers land on it, then return it. Shared by
        :meth:`_serve_nodb` and :meth:`_serve_db`, whose ``except HTTPException``
        arms used to carry this identical recovery (and comment) verbatim.
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

        Sets :attr:`registry` as a side effect and returns the open RO cursor.
        **Ownership transfers to the caller only on a clean return** — the
        ``finally`` in :meth:`_serve_db` then closes it. On failure this method
        closes the cursor it opened (the inlined predecessor relied on
        ``_serve_db``'s outer ``finally`` for that, which no longer sees the
        cursor when acquisition raises) and raises :class:`RegistryError`, which
        :meth:`Application.__call__` recovers from by serving db-less rather than
        surfacing a 500. A naive ``return cr`` extraction would leak the
        connection on this path; ``TestAcquireRegistryCursor`` (DB-free) locks
        the close-on-failure contract for every caught mode.

        The three caught arms convert a broken/absent database into that
        ``RegistryError``. The recovery contract is also guarded by the
        ``database_breaking`` suite in ``test_http/tests/test_registry.py``:

          * OperationalError — cannot connect / db gone (test_missing_db);
          * ProgrammingError — db present but schema broken: missing
            table/column/sequence (test_corrupt_ir_module_module_table,
            test_corrupt_signaling).

        AttributeError is a deliberately broad, *legacy* defensive arm (predates
        the http.py split; no dedicated test pins its exact trigger). It guards
        against observing a registry whose attributes are not yet populated —
        e.g. a re-entrant access during ``Registry.new``, which inserts the
        instance into ``Registry.registries`` before ``setup_signaling`` runs. It
        can also mask a genuine AttributeError bug in this cold
        registry-acquisition path, so before narrowing it re-run that suite to
        confirm recovery still holds.
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
                # The cursor we opened is ours until the clean ``return`` above;
                # close it here so a failure between cursor-open and that return
                # cannot leak the connection.
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
                    # Although the controller is marked read-only, it
                    # attempted a write operation. We do NOT raise — control
                    # falls through (no ``return``, no ``raise``) to the
                    # ``if cr.readonly: cr.close(); cr = ...cursor()`` block
                    # below, which swaps in a read/write cursor and retries.
                    # If a future maintainer adds an ``else``/``return`` here,
                    # the RW retry path is silently disabled.
                    _logger.warning(
                        "%s, retrying with a read/write cursor",
                        exc.args[0].rstrip(),
                        exc_info=True,
                    )
                    threading.current_thread().cursor_mode = "ro->rw"
                    # The read-only attempt already ran the endpoint, consuming
                    # any uploaded file streams (leaving them at EOF). Rewind
                    # them so the read/write retry below re-reads the body from
                    # the start instead of seeing an empty upload — mirroring
                    # what ``retrying`` does on a serialization retry.
                    self._rewind_input_files(exc)
                except Exception as exc:
                    # ``_update_served_exception`` attaches ``error_response``
                    # to ``exc`` as a side effect; the bare ``raise`` re-raises
                    # it preserving the original traceback (no self-referential
                    # ``__cause__``).
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
                # the cursor is already a RW cursor, start a new transaction
                # that will avoid repeatable read serialization errors because
                # check signaling is not done in `retrying` and that function
                # would just succeed the second time
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
        """Seek every uploaded file back to the start before re-dispatching.

        Once the request body has been read, its ``files`` streams sit at EOF;
        a retry that re-reads them would get empty content and silently drop the
        upload. Rewind the seekable ones and refuse — loudly — to retry on a
        non-seekable stream, the same contract
        :func:`odoo.service.transaction.retrying` enforces on a serialization
        retry. ``cause`` is chained onto the raised error for context.
        """
        for filename, file in self.httprequest.files.items():
            if hasattr(file, "seekable") and file.seekable():
                file.seek(0)
            else:
                msg = (
                    f"Cannot retry request on input file {filename!r} after a "
                    "read-only transaction error"
                )
                raise RuntimeError(msg) from cause

    def _update_served_exception(self, exc: Exception) -> None:
        """Attach an ``error_response`` to ``exc`` in place (side effect only).

        Callers re-raise ``exc`` themselves with a bare ``raise`` to preserve
        the original traceback, so this returns nothing. Two cases leave the
        exception untouched (no ``error_response`` attached) and let it bubble:

        * the abort+Response path (``HTTPException`` with ``code is None``),
          recovered by :meth:`_serve_db`;
        * ``--dev werkzeug`` for non-JSON routes — skip the styled
          ``ir.http._handle_error`` page so :meth:`Application.__call__` logs the
          full traceback and builds a plain response via
          ``dispatcher.handle_error``. (This fork serves via
          ``werkzeug.serving.make_server`` and does not wrap the app in
          ``werkzeug.debug.DebuggedApplication``, so no interactive debugger is
          reached; ``__call__`` is the actual handler of last resort.)
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
        """
        Called when no controller match the request path. Delegate to
        ``ir.http._serve_fallback`` to give modules the opportunity to
        find an alternative way to serve the request. In case no module
        provided a response, a generic 404 - Not Found page is returned.
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
        """
        Called when a controller match the request path. Delegate to
        ``ir.http`` to serve a response.
        """
        self.registry["ir.http"]._authenticate(rule.endpoint)
        self.registry["ir.http"]._pre_dispatch(rule, args)
        response = self.dispatcher.dispatch(rule.endpoint, args)
        self.registry["ir.http"]._post_dispatch(response)
        return response


# Late import to break the Request <-> Dispatcher cycle. Same pattern as
# request_class.py and dispatcher.py — see ``_checker_pep649`` for context.
from .dispatcher import (  # noqa: E402
    HttpDispatcher,
    JsonRPCDispatcher,
    _dispatchers,
)

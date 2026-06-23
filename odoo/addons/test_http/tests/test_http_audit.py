"""Regression guards from the http/ package audit.

These are DB-free unit tests (``BaseCase``):

* :class:`TestSessionStoreVacuum` locks the fix for the ``vacuum()`` method,
  which used to reach through the global ``root.session_store`` and ignore
  ``self``.
* :class:`TestProxyFacadeDrift` turns the *latent* drift risk of the
  hand-maintained werkzeug facade into a CI failure: ``ProxyAttr`` getters and
  the ``HTTPRequest`` attribute list resolve lazily, so a werkzeug rename or
  removal of a wrapped attribute would only surface at request time. Asserting
  every proxied attribute resolves on a live werkzeug instance catches that at
  test time instead. It also guards the opposite direction — a werkzeug upgrade
  that *adds* a public ``Request`` OR ``Response`` attribute the facade neither
  proxies nor explicitly excludes — via audited exclusion lists, so neither
  facade can silently fall behind werkzeug's public surface (the request side
  once trailed by 19 attrs; the response side had no coverage guard at all).
* :class:`TestSessionDebugCoercion` locks ``Session.debug`` to always read back
  as a ``str`` (a stored JSON ``null`` used to crash ``"assets" in debug`` on
  the static path).
* :class:`TestSessionContextNormalization` locks the load-time repair of a
  non-dict ``session.context`` (a stored JSON ``null`` used to 500 every request
  bearing that cookie).
* :class:`TestMonodbListCache` locks the per-host TTL memoisation of the
  database-less monodb-detection query.
* :class:`TestSerializeExceptionTraceback` locks the dev_mode/off-request gating
  of the server traceback in serialized error payloads.
* :class:`TestBestLangLocaleParsing` locks the ``best_lang`` fix for
  Accept-Language values carrying a locale modifier (``it-IT@euro``), which used
  to crash the 4-tuple unpack and degrade to en_US.
* :class:`TestServeRetryFileRewind` locks ``_rewind_input_files``: a
  read-only→read/write retry must re-read uploaded files instead of seeing an
  exhausted (empty) body.
* :class:`TestGeoipFailureCaching` locks the GeoIP failure-caching fix: a
  missing/invalid database is opened once, then ``None`` is cached and GeoIP
  degrades to an empty record.
* :class:`TestDbFilterRegexCache` locks the dbfilter regex memoisation.
* :class:`TestStreamNonRegularFile` locks the fix for a static URL resolving to a
  directory: the stream constructors now raise an ``OSError`` subclass (not a bare
  ``ValueError``) so ``_serve_static`` returns 404 instead of a 500.
* :class:`TestResponseLoadFname` locks that ``route_wrapper`` threads the endpoint
  name into ``Response.load`` so endpoint-misuse diagnostics name the offending
  controller instead of the useless literal ``<function>``.
* :class:`TestErrorPathEnvTolerance` locks the ``env``-presence guards on the
  error path: ``request.env`` is torn down before ``dispatcher.handle_error``
  runs, so ``redirect`` / ``set_cookie`` must key their ORM calls on ``env`` (not
  the still-set ``db``) and degrade gracefully instead of dereferencing
  ``None["ir.http"]``.
* :class:`TestRequestAppInjection` locks the ``Application`` injection seam:
  ``Request`` / ``GeoIP`` read their app from ``self.app`` (injected by
  ``Application.__call__`` as ``app=self``) rather than the ``root`` module
  singleton, so a test can supply its own app without monkeypatching the global;
  omitting ``app`` must still fall back to the singleton.
* :class:`TestApplicationCallHelpers` locks the helpers extracted from the
  decomposed ``Application.__call__`` (``_reset_thread_state``,
  ``_apply_proxy_fix``, ``_ensure_error_response``, ``_log_request_exception``),
  each now unit-testable in isolation instead of only through a full request.
"""

import os
import time
from pathlib import Path
from tempfile import TemporaryDirectory

import werkzeug.wrappers
from werkzeug.test import EnvironBuilder

from odoo.http import FilesystemSessionStore, Session, root
from odoo.http import wrappers as Hwrap
from odoo.tests.common import BaseCase, tagged


def _plant_old_session_file(store_path: str) -> Path:
    """Create an ancient session file under the scattered ``<dir>/ab/<sid>``
    layout and return its path."""
    sub = Path(store_path) / "ab"
    sub.mkdir(parents=True, exist_ok=True)
    fpath = sub / ("ab" + ("x" * 82))  # 84-char sid
    fpath.touch()
    old = time.time() - 10**9
    os.utime(fpath, (old, old))
    return fpath


@tagged("post_install", "-at_install")
class TestSessionStoreVacuum(BaseCase):
    """``vacuum()`` must operate on the store it is called on, not the global one."""

    def test_vacuum_uses_self_not_root_store(self):
        with TemporaryDirectory() as dir_self, TemporaryDirectory() as dir_root:
            file_self = _plant_old_session_file(dir_self)
            file_root = _plant_old_session_file(dir_root)

            store_self = FilesystemSessionStore(
                dir_self, session_class=Session, renew_missing=True
            )
            store_root = FilesystemSessionStore(
                dir_root, session_class=Session, renew_missing=True
            )

            # Make the global singleton point at a DIFFERENT store than the one
            # we vacuum. (cached_property override; restored in finally.)
            sentinel = object()
            prev = root.__dict__.get("session_store", sentinel)
            root.__dict__["session_store"] = store_root
            try:
                store_self.vacuum(max_lifetime=1)
            finally:
                if prev is sentinel:
                    root.__dict__.pop("session_store", None)
                else:
                    root.__dict__["session_store"] = prev

            self.assertFalse(
                file_self.exists(),
                "vacuum() should delete the calling store's own stale file",
            )
            self.assertTrue(
                file_root.exists(),
                "vacuum() must NOT touch a different store (the global root)",
            )


@tagged("post_install", "-at_install")
class TestProxyFacadeDrift(BaseCase):
    """The hand-maintained werkzeug facade must stay in sync with werkzeug."""

    # Public werkzeug ``Request`` attributes the ``HTTPRequest`` facade
    # deliberately does NOT proxy. The coverage test below fails if werkzeug
    # grows a public attribute that is neither proxied (added to
    # ``HTTPREQUEST_ATTRIBUTES``) nor listed here — forcing a conscious
    # proxy-or-exclude decision on every werkzeug upgrade. Each entry needs a
    # standing reason; group comments give it.
    _INTENTIONALLY_NOT_PROXIED = frozenset(
        {
            # werkzeug parsing / serialisation configuration (class & hook knobs),
            # not request data. Four of these (parameter_storage_class,
            # user_agent_class, max_form_memory_size, max_form_parts) ARE assigned
            # on the wrapped request in ``HTTPRequest.__init__`` but are never read
            # back through the facade, so they need no getter.
            "dict_storage_class",
            "list_storage_class",
            "parameter_storage_class",
            "form_data_parser_class",
            "make_form_data_parser",
            "want_form_data_parsed",
            "on_json_loading_failed",
            "json_module",
            "user_agent_class",
            "max_form_memory_size",
            "max_form_parts",
            # WSGI deployment flags (wsgi.multiprocess / multithread / run_once):
            # server topology, irrelevant to controllers.
            "is_multiprocess",
            "is_multithread",
            "is_run_once",
            # CORS *preflight request* headers. Odoo drives CORS from the request
            # method plus response headers (see ``Dispatcher.pre_dispatch``); it
            # never reads these request-side.
            "access_control_request_headers",
            "access_control_request_method",
            # Rarely-used request header (TRACE/OPTIONS hop limit).
            "max_forwards",
            # werkzeug internals / alternate constructors — meaningless on a
            # per-request wrapper instance.
            "application",
            "from_values",
            # The wrapper deliberately exposes its OWN ``environ`` — a filtered
            # copy (werkzeug/wsgi/socket keys stripped), with the unfiltered
            # original available as ``raw_environ`` — so werkzeug's must not be
            # proxied. ``shallow`` is a werkzeug body-access guard Odoo never uses.
            "environ",
            "shallow",
        }
    )

    def test_httprequest_attribute_list_resolves(self):
        # GET with no body so body-reading attrs (data/json/stream) don't raise
        # the unrelated ClientDisconnected.
        environ = EnvironBuilder(path="/x?q=1", method="GET").get_environ()
        wz = werkzeug.wrappers.Request(environ)
        od = Hwrap.HTTPRequest(environ)

        missing_on_werkzeug = []
        broken_on_wrapper = []
        for attr in Hwrap.HTTPREQUEST_ATTRIBUTES:
            if attr.startswith("__"):
                continue
            # Drift == the name no longer RESOLVES on werkzeug. Discriminate on
            # AttributeError only: properties like ``json`` raise
            # UnsupportedMediaType on a non-JSON request — that is a value-level
            # error (the attribute exists), not drift. ``hasattr`` would wrongly
            # propagate it.
            try:
                getattr(wz, attr)
            except AttributeError:
                missing_on_werkzeug.append(attr)
            except Exception:  # value-level errors are not drift
                pass
            try:
                getattr(od, attr)
            except AttributeError:
                broken_on_wrapper.append(attr)
            except Exception:  # body stream state is not drift
                pass

        self.assertFalse(
            missing_on_werkzeug,
            "HTTPREQUEST_ATTRIBUTES names attributes absent from werkzeug "
            f"Request (drift): {missing_on_werkzeug}",
        )
        self.assertFalse(
            broken_on_wrapper,
            f"HTTPRequest proxy attributes raise AttributeError: {broken_on_wrapper}",
        )

    def test_response_proxyattr_descriptors_resolve(self):
        response = Hwrap.Response(b"hi", status=200)
        # ProxyAttr descriptors were rewritten into ``property`` objects by
        # ``__set_name__``; ProxyFunc became plain functions (and are already
        # import-validated). The lazy/at-risk surface is the properties.
        proxy_props = [
            name
            for name, value in vars(Hwrap.Response).items()
            if isinstance(value, property) and not name.startswith("__")
        ]
        self.assertTrue(
            proxy_props, "expected ProxyAttr-derived properties on Response"
        )

        broken = []
        for name in proxy_props:
            try:
                getattr(response, name)
            except AttributeError:
                broken.append(name)
            except Exception:  # value-level errors are not drift
                pass
        self.assertFalse(
            broken,
            f"Response ProxyAttr properties raise AttributeError (werkzeug drift): {broken}",
        )

    def test_httprequest_proxy_covers_werkzeug_surface(self):
        """Every PUBLIC werkzeug Request attribute must be proxied OR excluded.

        ``test_httprequest_attribute_list_resolves`` only catches attrs that
        DISAPPEAR from werkzeug. This catches the opposite (and historically
        real) drift: a werkzeug upgrade ADDING a public attribute that then
        silently never reaches Odoo code through the facade — the failure mode
        that left 19 attributes unproxied when the http package was audited.
        """
        # Enumerate the INSTANCE surface, not the class: werkzeug's sansio
        # refactor stores method/path/headers/environ/... as instance
        # attributes (set in ``_SansIORequest.__init__``), so ``dir(Request)``
        # on the class omits them and would hide a real coverage gap.
        environ = EnvironBuilder(path="/x?q=1", method="GET").get_environ()
        public = {
            n for n in dir(werkzeug.wrappers.Request(environ)) if not n.startswith("_")
        }
        proxied = {n for n in Hwrap.HTTPREQUEST_ATTRIBUTES if not n.startswith("_")}
        excluded = self._INTENTIONALLY_NOT_PROXIED

        # An attribute must not be both proxied and listed as excluded.
        self.assertEqual(
            proxied & excluded,
            set(),
            "attributes are both proxied and excluded — pick one: "
            f"{sorted(proxied & excluded)}",
        )

        # The coverage guard: nothing public is left undecided.
        undecided = public - proxied - excluded
        self.assertEqual(
            undecided,
            set(),
            "werkzeug Request exposes public attribute(s) the HTTPRequest facade "
            "neither proxies nor excludes. Either add to HTTPREQUEST_ATTRIBUTES "
            "(to expose it) or to _INTENTIONALLY_NOT_PROXIED with a rationale: "
            f"{sorted(undecided)}",
        )

        # Keep the exclusion list honest: an excluded name werkzeug has since
        # removed is dead weight and hides the fact that it is gone.
        stale = excluded - public
        self.assertEqual(
            stale,
            set(),
            "_INTENTIONALLY_NOT_PROXIED lists attribute(s) no longer present on "
            f"werkzeug Request; remove them: {sorted(stale)}",
        )

    # Public werkzeug ``Response`` attributes the ``Response`` facade
    # deliberately does NOT proxy. Same contract as
    # ``_INTENTIONALLY_NOT_PROXIED`` above, for the response side: every public
    # werkzeug ``Response`` attribute must be either proxied (declared on the
    # ``Response`` proxy in ``wrappers.py``) or excluded here with a reason.
    # The request side had a coverage guard; the response side did not — so a
    # werkzeug upgrade adding a public ``Response`` attribute could silently
    # never reach Odoo code through the facade. This list closes that gap.
    _RESPONSE_INTENTIONALLY_NOT_PROXIED = frozenset(
        {
            # Per-header convenience accessors. Odoo reads/writes these through the
            # (proxied) ``response.headers`` mapping — the http layer sets CORS, CSP,
            # Vary, Date, etc. via ``headers.set(...)`` / ``headers[...] = ...`` (see
            # ``Dispatcher.pre_dispatch``, ``Application.set_csp``, ``Stream.get_response``),
            # never through werkzeug's typed header descriptors.
            "accept_ranges",
            "access_control_allow_credentials",
            "access_control_allow_headers",
            "access_control_allow_methods",
            "access_control_allow_origin",
            "access_control_expose_headers",
            "access_control_max_age",
            "allow",
            "content_language",
            "content_range",
            "content_security_policy",
            "content_security_policy_report_only",
            "cross_origin_embedder_policy",
            "cross_origin_opener_policy",
            "date",
            "mimetype_params",
            "vary",
            "www_authenticate",
            # WSGI serialisation internals / lifecycle. werkzeug calls these on the
            # wrapped ``_Response`` from inside ``__call__`` (which the proxy DOES
            # forward); they are never invoked through the proxy. ``close`` runs on
            # the ``ClosingIterator`` that ``__call__`` returns, not on the response
            # object — and ``call_on_close`` (for registering callbacks) IS proxied.
            "automatically_set_content_length",
            "calculate_content_length",
            "close",
            "get_app_iter",
            "get_wsgi_headers",
            "get_wsgi_response",
            "implicit_sequence_conversion",
            # Alternate constructor / serialiser config — meaningless on a per-
            # response wrapper instance. Odoo builds JSON via ``make_json_response``
            # / ``_fast_dumps``, not through ``response.json``'s module hook.
            "from_app",
            "json_module",
        }
    )

    def test_response_proxy_covers_werkzeug_surface(self):
        """Every PUBLIC werkzeug Response attribute must be proxied OR excluded.

        Mirror of ``test_httprequest_proxy_covers_werkzeug_surface`` for the
        response side, which previously had no coverage guard. ``Response`` is a
        :class:`~odoo.libs.facade.Proxy`: ``ProxyFunc`` declarations are resolved
        (and so import-validated) at class-definition time, and ``ProxyAttr``
        ones become properties — but neither mechanism notices a werkzeug upgrade
        that *adds* a public attribute. This asserts nothing public is left
        undecided.
        """
        # Enumerate the INSTANCE surface (werkzeug sets headers/status/... in
        # ``__init__``), consistent with the request-side test.
        wz_public = {
            n for n in dir(werkzeug.wrappers.Response("hi")) if not n.startswith("_")
        }
        # The proxy declares its mirrored attributes directly on the class
        # (ProxyAttr -> property, ProxyFunc -> function), plus odoo-only extras
        # (load/render/flatten/...). Those extras are harmless here: they are not
        # in werkzeug's public set, so they never affect the subtraction.
        proxied = {
            n
            for n, v in vars(Hwrap.Response).items()
            if not n.startswith("_")
            and (isinstance(v, (property, staticmethod, classmethod)) or callable(v))
        }
        excluded = self._RESPONSE_INTENTIONALLY_NOT_PROXIED

        self.assertEqual(
            proxied & excluded,
            set(),
            "Response attributes are both proxied and excluded — pick one: "
            f"{sorted(proxied & excluded)}",
        )

        undecided = wz_public - proxied - excluded
        self.assertEqual(
            undecided,
            set(),
            "werkzeug Response exposes public attribute(s) the Response facade "
            "neither proxies nor excludes. Either declare it on the Response "
            "proxy (wrappers.py) or add it to _RESPONSE_INTENTIONALLY_NOT_PROXIED "
            f"with a rationale: {sorted(undecided)}",
        )

        stale = excluded - wz_public
        self.assertEqual(
            stale,
            set(),
            "_RESPONSE_INTENTIONALLY_NOT_PROXIED lists attribute(s) no longer "
            f"present on werkzeug Response; remove them: {sorted(stale)}",
        )


def _make_json_request(body: bytes, content_type: str = "application/json"):
    """Build a standalone (no-db) :class:`Request` with the given JSON body."""
    from odoo.http import Request

    environ = EnvironBuilder(
        path="/x", method="POST", data=body, content_type=content_type
    ).get_environ()
    request = Request(Hwrap.HTTPRequest(environ))
    request.db = None
    request.params = {}
    return request


@tagged("post_install", "-at_install")
class TestDispatcherBehaviour(BaseCase):
    """Lock the dispatcher refactors: shared ``_call_endpoint`` and the explicit
    JSON-RPC body validation that replaced AttributeError-catching."""

    def test_jsonrpc_rejects_non_object_body(self):
        import werkzeug.exceptions

        from odoo.http import JsonRPCDispatcher

        cases = [
            (b"[1, 2, 3]", "Invalid JSON-RPC data"),
            (b"42", "Invalid JSON-RPC data"),
            (b'"hi"', "Invalid JSON-RPC data"),
            (b"null", "Invalid JSON-RPC data"),
            (b"{bad", "Invalid JSON data"),
        ]
        for body, expected in cases:
            request = _make_json_request(body)
            with self.assertRaises(werkzeug.exceptions.HTTPException) as cm:
                JsonRPCDispatcher(request).dispatch(lambda **kw: kw, {})
            response = cm.exception.get_response()
            self.assertEqual(response.status_code, 400, body)
            self.assertIn(expected, response.get_data(as_text=True), body)

    def test_json2_rejects_non_object_body(self):
        import werkzeug.exceptions

        from odoo.http import Json2Dispatcher

        for body in (b"[1, 2, 3]", b"42", b'"hi"'):
            request = _make_json_request(body)
            with self.assertRaises(werkzeug.exceptions.BadRequest):
                Json2Dispatcher(request).dispatch(lambda **kw: kw, {})

    def test_nodb_dispatch_calls_endpoint_with_merged_params(self):
        from odoo.http import JsonRPCDispatcher

        request = _make_json_request(b'{"params": {"a": 1}, "id": 7}')
        captured = {}

        def endpoint(**kw):
            captured.update(kw)
            return {"ok": True}

        JsonRPCDispatcher(request).dispatch(endpoint, {"b": 2})
        self.assertEqual(captured, {"a": 1, "b": 2})

    def test_call_endpoint_routes_through_irhttp_when_db(self):
        from odoo.http import JsonRPCDispatcher

        request = _make_json_request(b'{"params": {"a": 1}}')
        request.db = "fake-db"
        seen = []

        class _FakeIrHttp:
            @classmethod
            def _dispatch(cls, endpoint):
                seen.append(endpoint)
                return endpoint(**request.params)

        request.registry = {"ir.http": _FakeIrHttp}
        JsonRPCDispatcher(request).dispatch(lambda **kw: {"got": kw}, {})
        self.assertEqual(len(seen), 1, "db path must route through ir.http._dispatch")


@tagged("post_install", "-at_install")
class TestIrHttpContract(BaseCase):
    """``HttpExtension`` must stay an ACCURATE, ENFORCED contract for ir.http.

    No type checker is configured in this fork, so the Protocol would otherwise
    be unverified documentation. This test makes drift fail in CI: a method
    added to/removed from ir.http, or an arity change, breaks here.
    """

    @staticmethod
    def _required_positional(func, *, drop_first_self):
        import inspect

        params = list(inspect.signature(func).parameters.values())
        if drop_first_self and params and params[0].name in ("self", "cls"):
            params = params[1:]
        return [
            p
            for p in params
            if p.default is p.empty
            and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
        ]

    def test_irhttp_satisfies_httpextension(self):
        from odoo.http import HttpExtension

        from odoo.addons.base.models.ir_http import IrHttp

        # runtime_checkable + methods-only protocol -> issubclass checks presence
        self.assertTrue(
            issubclass(IrHttp, HttpExtension),
            "IrHttp no longer provides every method declared by HttpExtension",
        )

        for name in HttpExtension.__protocol_attrs__:
            proto_req = self._required_positional(
                getattr(HttpExtension, name), drop_first_self=True
            )
            # getattr on a classmethod yields a bound method whose signature
            # already excludes cls; instance methods (routing_map) still carry
            # self, so drop a leading self/cls in both cases.
            impl_req = self._required_positional(
                getattr(IrHttp, name), drop_first_self=True
            )
            self.assertEqual(
                len(proto_req),
                len(impl_req),
                f"{name}: required-arg arity drift "
                f"(HttpExtension {len(proto_req)} vs ir.http {len(impl_req)})",
            )


def _make_request(path="/x", method="GET", headers=None, data=None, content_type=None):
    """Build a standalone (no-db) :class:`Request` from a WSGI environ."""
    from odoo.http import Request

    kwargs = {"path": path, "method": method, "headers": headers or {}}
    if data is not None:
        kwargs["data"] = data
    if content_type is not None:
        kwargs["content_type"] = content_type
    environ = EnvironBuilder(**kwargs).get_environ()
    return Request(Hwrap.HTTPRequest(environ))


@tagged("post_install", "-at_install")
class TestBestLangLocaleParsing(BaseCase):
    """``best_lang`` must survive an Accept-Language carrying a locale modifier.

    ``babel.core.parse_locale`` returns a 5-tuple for values like ``it-IT@euro``
    — and a client CAN send that; werkzeug surfaces it verbatim via
    ``accept_languages.best``. The old 4-tuple unpack raised ValueError and
    silently degraded to en_US; the ``[:2]`` slice resolves the locale instead.
    """

    def _best_lang(self, accept_language):
        return _make_request(headers={"Accept-Language": accept_language}).best_lang

    def test_modifier_locale_resolves(self):
        self.assertEqual(self._best_lang("it-IT@euro,en;q=0.8"), "it_IT")

    def test_plain_locale_unaffected(self):
        self.assertEqual(self._best_lang("en-US,en;q=0.9"), "en_US")

    def test_language_only_uses_alias(self):
        # 'fr' has no territory; babel's LOCALE_ALIASES maps it to fr_FR.
        self.assertEqual(self._best_lang("fr"), "fr_FR")

    def test_unknown_language_degrades_to_none(self):
        # 'tlh' (Klingon) is a valid tag but absent from babel's LOCALE_ALIASES;
        # best_lang returns None and default_lang() falls back to DEFAULT_LANG.
        request = _make_request(headers={"Accept-Language": "tlh"})
        self.assertIsNone(request.best_lang)
        self.assertEqual(request.default_lang(), "en_US")


@tagged("post_install", "-at_install")
class TestServeRetryFileRewind(BaseCase):
    """A read-only→read/write retry must re-read uploaded files from the start.

    The read-only attempt consumes the upload stream; without a rewind the RW
    retry sees an empty body and silently drops the file. ``_rewind_input_files``
    seeks seekable uploads back to 0 and refuses (RuntimeError) on a
    non-seekable stream — the same contract as ``service.transaction.retrying``.
    """

    def test_rewind_restores_consumed_upload(self):
        import io

        request = _make_request(
            method="POST", data={"upload": (io.BytesIO(b"PAYLOAD-1234"), "f.bin")}
        )
        # The read-only attempt reads the upload, leaving the stream at EOF.
        self.assertEqual(request.httprequest.files["upload"].read(), b"PAYLOAD-1234")
        self.assertEqual(request.httprequest.files["upload"].read(), b"")
        # The RW retry rewinds, so the body is readable again from the start.
        request._rewind_input_files()
        self.assertEqual(request.httprequest.files["upload"].read(), b"PAYLOAD-1234")

    def test_rewind_refuses_non_seekable(self):
        import werkzeug.datastructures

        request = _make_request(method="POST")

        class _NonSeekable:
            def seekable(self):
                return False

        request.httprequest._HTTPRequest__wrapped.files = (
            werkzeug.datastructures.MultiDict({"bad": _NonSeekable()})
        )
        with self.assertRaises(RuntimeError):
            request._rewind_input_files(ValueError("read-only transaction"))


@tagged("post_install", "-at_install")
class TestGeoipFailureCaching(BaseCase):
    """A missing/invalid GeoIP database is opened once (then ``None`` is cached),
    and GeoIP degrades to an empty record instead of raising."""

    def test_failed_db_load_is_cached(self):
        from unittest.mock import patch

        from odoo.http import root
        from odoo.http.constants import geoip2
        from odoo.tools import config, reset_cached_properties

        if geoip2 is None:
            self.skipTest("geoip2 not installed")

        attempts = {"n": 0}
        real_reader = geoip2.database.Reader

        class _CountingReader(real_reader):
            def __init__(self, *args, **kwargs):
                attempts["n"] += 1
                super().__init__(*args, **kwargs)  # OSError: file missing

        reset_cached_properties(root)
        self.addCleanup(reset_cached_properties, root)
        with (
            patch.object(
                config,
                "options",
                config.options.new_child({"geoip_city_db": "/nonexistent/city.mmdb"}),
            ),
            patch.object(geoip2.database, "Reader", _CountingReader),
        ):
            self.assertIsNone(root.geoip_city_db)
            self.assertIsNone(root.geoip_city_db)
            self.assertIsNone(root.geoip_city_db)
        self.assertEqual(
            attempts["n"], 1, "a missing GeoIP DB must be opened once, then cached"
        )

    def test_geoip_degrades_when_db_unavailable(self):
        from odoo.http import root
        from odoo.http.geoip import GeoIP
        from odoo.tools import reset_cached_properties

        reset_cached_properties(root)
        self.addCleanup(reset_cached_properties, root)
        # Pin both readers to the cached-None failure state.
        root.__dict__["geoip_city_db"] = None
        root.__dict__["geoip_country_db"] = None

        geoip = GeoIP("1.2.3.4")
        self.assertIsNone(geoip.country_code)
        self.assertIsNone(geoip.country_name)
        self.assertFalse(bool(geoip))


@tagged("post_install", "-at_install")
class TestGeoipNullContract(BaseCase):
    """With geoip2 NOT installed, the scalar/dict GeoIP API must still return
    ``None`` for unresolved leaves — never the chainable ``_GeoIPNull`` sentinel.

    When geoip2 is absent, ``GEOIP_EMPTY_COUNTRY``/``GEOIP_EMPTY_CITY`` are the
    chainable ``_GEOIP_NULL`` sentinel so that intermediate access
    (``geoip.country.iso_code``) never raises. But a *leaf* scalar leaked that
    sentinel instead of ``None``: it is ``is not None`` (guards miss it), not
    JSON-serialisable, and — the reachable failure — psycopg cannot adapt it as a
    SQL parameter, so ``website.visitor``'s ``country_code`` upsert (which binds
    ``request.geoip.get('country_code')`` straight into a query) broke for every
    anonymous visitor on a geoip2-less deployment. ``_none_if_null`` coerces the
    sentinel at the leaf; a genuine ``0`` (equator latitude) is preserved.
    """

    def _absent_geoip(self):
        from unittest.mock import patch

        from odoo.http import geoip as geoip_mod
        from odoo.http import root
        from odoo.http.constants import _GEOIP_NULL
        from odoo.tools import reset_cached_properties

        reset_cached_properties(root)
        self.addCleanup(reset_cached_properties, root)
        root.__dict__["geoip_city_db"] = None
        root.__dict__["geoip_country_db"] = None
        # Simulate the geoip2-absent state: the empty records are the sentinel.
        for attr in ("GEOIP_EMPTY_COUNTRY", "GEOIP_EMPTY_CITY"):
            p = patch.object(geoip_mod, attr, _GEOIP_NULL)
            p.start()
            self.addCleanup(p.stop)
        return geoip_mod.GeoIP("1.2.3.4")

    def test_scalar_leaves_are_none_not_sentinel(self):
        import json

        geoip = self._absent_geoip()
        for value in (
            geoip.country_code,
            geoip.country_name,
            geoip.get("country_code"),
            geoip.get("city"),
            geoip["latitude"],
            geoip["time_zone"],
            geoip["region"],
        ):
            self.assertIsNone(value)
            # JSON-serialisable (the sentinel was not).
            self.assertEqual(json.dumps(value), "null")
        self.assertFalse(bool(geoip))

    def test_real_zero_value_is_preserved(self):
        # ``_none_if_null`` must only map the sentinel to None — a real 0.0 leaf
        # (a latitude on the equator) must survive, not collapse to None.
        from odoo.http.geoip import _none_if_null

        self.assertEqual(_none_if_null(0.0), 0.0)
        self.assertEqual(_none_if_null(0), 0)
        self.assertEqual(_none_if_null(""), "")
        self.assertIsNone(_none_if_null(None))


@tagged("post_install", "-at_install")
class TestDbFilterRegexCache(BaseCase):
    """The dbfilter regex is compiled once per (pattern, host) and still
    performs the documented ``%h`` / ``%d`` substitution."""

    def test_compiled_regex_is_cached(self):
        from odoo.http.helpers import _compiled_dbfilter

        _compiled_dbfilter.cache_clear()
        first = _compiled_dbfilter(r"^%d$", "acme.example.com:80")
        again = _compiled_dbfilter(r"^%d$", "acme.example.com:80")
        self.assertIs(first, again, "same (pattern, host) must reuse the regex")
        other_host = _compiled_dbfilter(r"^%d$", "other.example.com")
        self.assertIsNot(first, other_host, "a different host compiles a new regex")

    def test_host_and_domain_substitution(self):
        from odoo.http.helpers import _compiled_dbfilter

        # %d -> first domain label; %h -> full host with ``www.`` and :port stripped
        domain_re = _compiled_dbfilter(r"^%d$", "www.acme.example.com:8069")
        self.assertTrue(domain_re.match("acme"))
        self.assertFalse(domain_re.match("acme.example.com"))
        host_re = _compiled_dbfilter(r"^%h$", "www.acme.example.com:8069")
        self.assertTrue(host_re.match("acme.example.com"))


@tagged("post_install", "-at_install")
class TestEnsureDbRouteConstant(BaseCase):
    """The ensure_db path list lives in one documented constant."""

    def test_constant_contains_core_routes(self):
        from odoo.http.constants import ENSURE_DB_PATH_PREFIX, ENSURE_DB_PATHS

        self.assertEqual(ENSURE_DB_PATH_PREFIX, "/odoo/")
        self.assertLessEqual({"/odoo", "/web", "/web/login"}, ENSURE_DB_PATHS)
        self.assertIsInstance(ENSURE_DB_PATHS, frozenset)


@tagged("post_install", "-at_install")
class TestSessionDebugCoercion(BaseCase):
    """``Session.debug`` must always read back as a ``str``.

    ``_handle_debug`` only ever stores a string and the default is ``""``, but a
    hand-edited or cross-version session file can carry ``"debug": null``;
    ``setdefault`` will not overwrite that ``None``. ``Request._serve_static``
    then evaluates ``"assets" in self.session.debug`` and a ``None`` would raise
    ``TypeError`` — a 500 on a static asset. The getter coerces ``None`` to
    ``""`` so every reader (and the ``typeof o.debug === "string"`` JS guard)
    sees the contract it assumes.
    """

    def test_none_debug_reads_as_empty_string(self):
        from odoo.http.constants import get_default_session
        from odoo.http.session import Session

        # Simulate loading a session file with an explicit JSON null debug, then
        # the default-key backfill that _get_session_and_dbname performs.
        session = Session({"debug": None}, "x" * 84)
        for key, val in get_default_session().items():
            session.setdefault(key, val)

        self.assertEqual(session.debug, "")
        # The exact expression from Request._serve_static must not raise.
        self.assertFalse("assets" in session.debug)

    def test_missing_debug_reads_as_empty_string(self):
        from odoo.http.session import Session

        self.assertEqual(Session({}, "x" * 84).debug, "")

    def test_real_debug_value_preserved(self):
        from odoo.http.session import Session

        session = Session({}, "x" * 84)
        session.debug = "assets"
        self.assertEqual(session.debug, "assets")
        self.assertTrue("assets" in session.debug)


@tagged("post_install", "-at_install")
class TestSessionContextNormalization(BaseCase):
    """``request.session.context`` must be a mutable dict after session load.

    A hand-edited / cross-version session file with ``"context": null`` is not
    repaired by ``setdefault`` (the key exists). ``_get_session_and_dbname`` then
    does ``session.context.get("lang")`` and every later in-place
    ``session.context[...] = ...`` would raise AttributeError — a 500 on EVERY
    request for that cookie (the main path). The getter cannot coerce on read
    (callers depend on the identity of the stored dict for in-place writes), so
    the load path normalises a non-dict context to a fresh dict once. This
    exercises the real ``_get_session_and_dbname`` rather than a copy.
    """

    def test_null_context_is_normalised_and_mutable(self):
        from unittest.mock import patch

        from odoo.http import root
        from odoo.http.session import Session

        request = _make_request(path="/x")
        planted = Session({"context": None, "db": None}, "x" * 84)

        # No session cookie -> the store's ``new()`` supplies the session; pin
        # db discovery to "no db" so the path is deterministic and DB-free.
        with (
            patch.object(root.session_store, "new", return_value=planted),
            patch("odoo.http.request_class.db_list", return_value=[]),
        ):
            request._post_init()

        self.assertIsInstance(
            request.session.context, dict, "null context must become a dict"
        )
        self.assertEqual(request.session.context.get("lang"), "en_US")
        # The normalised dict is the stored object, so in-place writes persist.
        request.session.context["tz"] = "UTC"
        self.assertEqual(request.session.context["tz"], "UTC")


@tagged("post_install", "-at_install")
class TestMonodbListCache(BaseCase):
    """``_monodb_dblist`` memoises the per-host ``pg_database`` query.

    The database-less request fast path (``_get_session_and_dbname``) used to run
    ``db_list(force=True)`` — a catalog query — on every anonymous request. The
    cached variant collapses a burst to one query per host per TTL bucket while
    leaving the shared ``db_list`` (DB manager / cron existence checks) uncached.
    It lives in ``request_class`` so the test infra's ``db_list`` monkeypatch
    (``odoo.http.request_class.db_list``) stays the live binding.
    """

    def setUp(self):
        super().setUp()
        from odoo.http import request_class

        request_class.clear_monodb_cache()
        self.addCleanup(request_class.clear_monodb_cache)

    def test_same_host_and_bucket_queries_once(self):
        from unittest.mock import patch

        from odoo.http import request_class

        calls = []

        def fake(force, host):
            calls.append((force, host))
            return [f"db_{host}"]

        with patch.object(request_class, "db_list", side_effect=fake):
            request_class._monodb_dblist_cached("acme", 100)
            request_class._monodb_dblist_cached("acme", 100)  # same bucket -> cached
            request_class._monodb_dblist_cached("acme", 101)  # new bucket -> refetch
            request_class._monodb_dblist_cached("other", 100)  # new host -> refetch

        # 3 underlying queries: acme@100, acme@101, other@100 (the repeat is cached)
        self.assertEqual(len(calls), 3, calls)
        self.assertEqual([c[1] for c in calls], ["acme", "acme", "other"])

    def test_ttl_constant_is_positive(self):
        from odoo.http.constants import DB_MONODB_CACHE_TTL

        # The public wrapper keys on int(time()//TTL); a non-positive TTL would
        # make the bucket math degenerate (ZeroDivision / never-expiring).
        self.assertGreater(DB_MONODB_CACHE_TTL, 0)

    def test_public_wrapper_returns_fresh_mutable_list(self):
        from unittest.mock import patch

        from odoo.http import request_class

        with patch.object(request_class, "db_list", return_value=["only"]):
            first = request_class._monodb_dblist("h")
            first.append("MUTATED")  # must not corrupt the cached entry
            second = request_class._monodb_dblist("h")  # same bucket -> cached

        self.assertEqual(
            second, ["only"], "cached tuple must be immune to caller mutation"
        )
        self.assertIsInstance(second, list)


@tagged("post_install", "-at_install")
class TestSerializeExceptionTraceback(BaseCase):
    """``serialize_exception`` must not leak the server traceback to clients.

    The full traceback (filesystem paths, code structure) is included off-request
    (cron / server-side callers read by admins) and in ``dev_mode``, but a normal
    production HTTP error response gets a short note instead. The ``debug`` key is
    always present (response shape is pinned by ``test_webjson2`` /
    ``test_error``), and gating never queries the DB (the error path may run on a
    broken cursor).
    """

    @staticmethod
    def _serialize():
        from odoo.http import serialize_exception

        try:
            raise ValueError("boom")
        except ValueError as exc:
            return serialize_exception(exc)

    def test_offrequest_includes_full_traceback(self):
        # No request on the stack in a BaseCase -> server-side caller (cron/log).
        payload = self._serialize()
        self.assertIn("Traceback (most recent call last)", payload["debug"])

    def test_production_request_hides_traceback_keeps_shape(self):
        from unittest.mock import patch

        from odoo.http.core import _request_stack
        from odoo.tools import config

        request = _make_request(path="/x")
        _request_stack.push(request)
        try:
            with patch.object(
                config, "options", config.options.new_child({"dev_mode": []})
            ):
                payload = self._serialize()
        finally:
            _request_stack.pop()

        # The placeholder itself contains the word "Traceback", so assert on the
        # actual traceback marker instead.
        self.assertNotIn("most recent call last", payload["debug"])
        self.assertIn("hidden", payload["debug"])
        self.assertEqual(
            set(payload), {"name", "message", "arguments", "context", "debug"}
        )

    def test_dev_mode_request_includes_traceback(self):
        from unittest.mock import patch

        from odoo.http.core import _request_stack
        from odoo.tools import config

        request = _make_request(path="/x")
        _request_stack.push(request)
        try:
            with patch.object(
                config, "options", config.options.new_child({"dev_mode": ["all"]})
            ):
                payload = self._serialize()
        finally:
            _request_stack.pop()

        self.assertIn("Traceback (most recent call last)", payload["debug"])


@tagged("post_install", "-at_install")
class TestStreamNonRegularFile(BaseCase):
    """A static URL resolving to a non-regular file (a directory) must 404, not 500.

    ``tools.file_path`` validates existence with ``Path.exists()``, which is True
    for directories, so ``Application.get_static_file`` happily hands a directory
    path to ``Stream._from_trusted_path``. That used to ``raise ValueError`` for a
    non-regular file; ``Request._serve_static`` only catches ``OSError``, so the
    ValueError escaped to the WSGI entrypoint as a 500 (with an ERROR-level
    traceback) on any probe of e.g. ``/web/static/src``. The constructors now
    raise an ``OSError`` subclass so the existing 404 handler covers it.
    """

    def test_from_trusted_path_directory_raises_oserror(self):
        from odoo.http import Stream

        with TemporaryDirectory() as d:
            # The fix: an OSError subclass, NOT a bare ValueError.
            with self.assertRaises(OSError):
                Stream._from_trusted_path(d, public=True)
            with self.assertRaises(IsADirectoryError):
                Stream._from_trusted_path(d, public=True)

    def test_from_path_directory_raises_oserror(self):
        # ``test_http/tests`` is a real package directory under the addons tree,
        # so ``file_path`` resolves it and the non-regular-file guard fires.
        from odoo.http import Stream

        with self.assertRaises(OSError):
            Stream.from_path("test_http/tests", public=True)

    def test_serve_static_directory_is_404(self):
        import werkzeug.exceptions

        from odoo.http import Request

        with TemporaryDirectory() as d:
            environ = EnvironBuilder(path="/web/static/src").get_environ()
            request = Request(Hwrap.HTTPRequest(environ))
            # The trusted-path branch mimics get_static_file() resolving a dir.
            with self.assertRaises(werkzeug.exceptions.NotFound):
                request._serve_static(d)

    def test_serve_static_regular_file_still_streams(self):
        from pathlib import Path

        from odoo.http import Request
        from odoo.http.core import _request_stack

        with TemporaryDirectory() as d:
            f = Path(d, "real.txt")
            f.write_text("hello")
            environ = EnvironBuilder(path="/web/static/real.txt").get_environ()
            request = Request(Hwrap.HTTPRequest(environ))
            # ``_serve_static`` reads ``session.debug``; the path-stream
            # ``get_response`` reads the active request's environ via the proxy.
            request.session = Session({"debug": ""}, "s" * 84)
            _request_stack.push(request)
            try:
                response = request._serve_static(str(f))
            finally:
                _request_stack.pop()
            # 200, not a 404/500: the regular-file path is unaffected by the fix.
            # (The body is a direct-passthrough file stream, so it is not read here.)
            self.assertEqual(response.status_code, 200)


@tagged("post_install", "-at_install")
class TestRouteParamFilter(BaseCase):
    """``route_wrapper`` precomputes the endpoint param-filter once instead of
    calling ``inspect.signature`` (via ``filter_kwargs``) on every request.
    Lock that the precomputed filter is byte-for-byte equivalent to
    ``filter_kwargs`` across the parameter-kind matrix, so the optimisation
    cannot silently drift from the shared helper it replaced."""

    def _endpoints(self):
        def no_args(self):
            pass

        def positional(self, a, b):
            pass

        def with_defaults(self, a, b=1):
            pass

        def kw_only(self, a, *, b, c=3):
            pass

        def var_keyword(self, a, **kw):
            pass

        def var_positional(self, a, *rest):
            pass

        def pos_only(self, a, /, b):
            pass

        def everything(self, a, b=2, /, c=3, *rest, d, e=5, **kw):
            pass

        return [
            no_args,
            positional,
            with_defaults,
            kw_only,
            var_keyword,
            var_positional,
            pos_only,
            everything,
        ]

    def test_matches_filter_kwargs(self):
        from odoo.http.routing import _route_param_filter
        from odoo.libs.func import filter_kwargs

        sample_kwargs = {"a": 1, "b": 2, "c": 3, "d": 4, "e": 5, "rest": 6, "z": 9}
        for endpoint in self._endpoints():
            accepts_var_kw, accepted, _bound_self = _route_param_filter(endpoint)
            if accepts_var_kw:
                got = sample_kwargs
            else:
                got = {k: v for k, v in sample_kwargs.items() if k in accepted}
            expected = filter_kwargs(endpoint, sample_kwargs)
            self.assertEqual(
                got,
                expected,
                f"precomputed filter diverged from filter_kwargs for {endpoint.__name__}",
            )

    def test_ignored_args_set_is_identical(self):
        """The 'called ignoring args {...}' warning content must be preserved."""
        from odoo.http.routing import _route_param_filter
        from odoo.libs.func import filter_kwargs

        params = {"a": 1, "session_id": "x", "debug": "1"}
        for endpoint in self._endpoints():
            accepts_var_kw, accepted, _bound_self = _route_param_filter(endpoint)
            new_ko = set() if accepts_var_kw else (params.keys() - accepted)
            old_ko = set(params) - set(filter_kwargs(endpoint, params))
            self.assertEqual(new_ko, old_ko, endpoint.__name__)


@tagged("post_install", "-at_install")
class TestResponseLoadFname(BaseCase):
    """``route_wrapper`` must thread the endpoint name into ``Response.load``.

    ``_Response.load`` logs the *function name* when an endpoint misbehaves
    (returns an ``HTTPException`` instead of raising it, or returns an invalid
    type). ``route_wrapper`` precomputes that name as ``fname`` but used to call
    ``Response.load(result)`` without it, so every such diagnostic reported the
    useless literal ``<function>``. This locks the name through.
    """

    def _wrap_returning(self, result):
        """A real ``@route``-decorated endpoint whose body returns ``result``."""
        from odoo.http import route

        @route("/audit-fname", type="http", auth="none")
        def the_endpoint(self):
            return result

        return the_endpoint  # this is route_wrapper

    def test_returned_httpexception_names_the_endpoint(self):
        import werkzeug.exceptions

        wrapper = self._wrap_returning(werkzeug.exceptions.NotFound())
        with self.assertLogs("odoo.http.wrappers", level="WARNING") as logs:
            with self.assertRaises(werkzeug.exceptions.NotFound):
                wrapper(object())
        msg = "\n".join(logs.output)
        self.assertIn("the_endpoint", msg, "the offending endpoint must be named")
        self.assertNotIn(
            "<function>", msg, "the useless default placeholder must not leak"
        )

    def test_invalid_return_type_names_the_endpoint(self):
        wrapper = self._wrap_returning(object())  # not str/bytes/None/Response
        with self.assertRaises(TypeError) as cm:
            wrapper(object())
        self.assertIn("the_endpoint", str(cm.exception))
        self.assertNotIn("<function>", str(cm.exception))


@tagged("post_install", "-at_install")
class TestErrorPathEnvTolerance(BaseCase):
    """The error path runs response helpers AFTER ``request.env`` is torn down.

    ``_serve_db``'s ``finally`` nulls ``request.env`` before
    ``Application.__call__`` invokes ``dispatcher.handle_error`` (e.g. the
    SessionExpired branch redirects to ``/web/login`` and sets a cookie), where
    ``request.db`` is still truthy. Helpers that keyed an ORM call on ``db``
    instead of ``env`` then dereferenced ``None["ir.http"]`` →
    ``TypeError: 'NoneType' object is not subscriptable``. These lock the
    ``env``-presence guards so the error path degrades gracefully.
    """

    def _push_envless_db_request(self):
        """A live Request with a selected db but no env (the torn-down state)."""
        from odoo.http import _request_stack

        request = _make_request(path="/web/login")
        request.db = "audit-db"
        request.env = None
        _request_stack.push(request)
        self.addCleanup(_request_stack.pop)
        return request

    def test_redirect_falls_back_to_werkzeug_without_env(self):
        request = self._push_envless_db_request()
        # Pre-fix: ``self.env["ir.http"]._redirect`` raised TypeError here.
        response = request.redirect("/web/login")
        self.assertEqual(response.status_code, 303)
        self.assertTrue(
            response.headers["Location"].endswith("/web/login"),
            response.headers.get("Location"),
        )

    def test_set_cookie_skips_consent_check_without_env(self):
        from odoo.http.wrappers import _Response

        self._push_envless_db_request()
        response = _Response()
        # Pre-fix: ``request.env["ir.http"]._is_allowed_cookie`` raised TypeError.
        response.set_cookie("session_id", "abc", max_age=100, httponly=True)
        set_cookie = response.headers.get("Set-Cookie") or ""
        self.assertIn("session_id=abc", set_cookie)

    def test_apply_cookie_defaults_unit_guard(self):
        from odoo.http.wrappers import _apply_cookie_defaults

        self._push_envless_db_request()
        # db truthy + env None must NOT dereference None["ir.http"].
        _expires, max_age, _secure, samesite = _apply_cookie_defaults(
            -1, 100, "required", None, None
        )
        self.assertEqual(max_age, 100, "required cookie must survive the env-less path")
        self.assertEqual(samesite, "Lax")


@tagged("post_install", "-at_install")
class TestSelfParamCollision(BaseCase):
    """A request arg named ``self`` must not crash the endpoint.

    ``route_wrapper`` binds the controller instance positionally. It used to
    name that parameter ``self`` and ``_route_param_filter`` kept ``self`` in
    the accepted set, so a request arg literally named ``self`` (an attacker can
    send ``?self=1`` to any route) collided with the bound instance and raised
    ``TypeError: ... got multiple values for argument 'self'`` — a 500 on every
    ``http``/``jsonrpc`` route. The wrapper's bound parameter is now
    positional-only and not named ``self``, and the endpoint's first parameter
    is excluded from the accepted set, so such an arg is ignored, not fatal.
    """

    def _wrap(self, fn):
        """Return the ``route_wrapper`` for ``fn`` (a raw @route decoration)."""
        from odoo.http import route

        return route("/x", type="http", auth="none")(fn)

    def _body(self, response):
        return response.get_data(as_text=True)

    def test_var_keyword_endpoint_ignores_self(self):
        wrapper = self._wrap(lambda self, name=None, **kw: f"{name}|{sorted(kw)}")
        # object() stands in for the bound controller instance.
        with self.assertLogs("odoo.http.routing", level="WARNING") as cm:
            response = wrapper(object(), self="attacker", name="bob")
        self.assertEqual(self._body(response), "bob|[]")
        self.assertIn("ignoring args", "\n".join(cm.output))
        self.assertIn("self", "\n".join(cm.output))

    def test_explicit_arg_endpoint_ignores_self(self):
        wrapper = self._wrap(lambda self, name: f"hi {name}")
        with self.assertLogs("odoo.http.routing", level="WARNING"):
            response = wrapper(object(), self="attacker", name="bob")
        self.assertEqual(self._body(response), "hi bob")

    def test_normal_params_unaffected(self):
        wrapper = self._wrap(lambda self, name=None, **kw: f"{name}|{sorted(kw)}")
        self.assertEqual(self._body(wrapper(object(), name="bob")), "bob|[]")
        # an arbitrary extra arg still flows into **kw (not dropped as 'self' is)
        self.assertEqual(
            self._body(wrapper(object(), name="bob", extra="1")),
            "bob|['extra']",
        )

    def test_filter_excludes_only_first_param(self):
        from odoo.http.routing import _route_param_filter

        def endpoint(self, a, b, *, c):
            pass

        accepts_var_kw, accepted, bound_self = _route_param_filter(endpoint)
        self.assertFalse(accepts_var_kw)
        self.assertEqual(bound_self, "self")
        self.assertNotIn("self", accepted)
        self.assertEqual(accepted, frozenset({"a", "b", "c"}))


@tagged("post_install", "-at_install")
class TestRouteWithoutRouteWarning(BaseCase):
    """The "controller endpoint without any route" warning must name a REAL,
    navigable class — not the leaked loop variable.

    ``_generate_routing_rules`` iterated ``for cls in unique(ancestors)`` and
    then used the leaked ``cls`` in the route-less warning. That variable is the
    LAST ancestor — the synthetic merged controller built by ``type(name, ...)``
    in this module — so the message reported ``odoo.http.routing.<name>`` (wrong
    module) with a name that could read ``A (extended by B)`` (not importable).
    It now names the most-derived ancestor that actually declared the @route.
    """

    def _make_route_less_tree(self, module):
        """Build ``A(Controller)`` with a @route()'d method that declares NO
        path, plus ``B(A)`` that doesn't redefine it — both reporting ``module``
        as their addon. Built with ``type()`` (not ``exec``) so ``__module__``
        is set before ``Controller.__init_subclass__`` registers them; the
        bucket is restored on cleanup so other tests are unaffected.
        """
        from odoo.http import Controller, route

        before = list(Controller.children_classes.get(module, []))
        self.addCleanup(Controller.children_classes.__setitem__, module, before)
        modpath = f"odoo.addons.{module}.controllers"

        def meth(self):
            return "x"

        a_cls = type("A", (Controller,), {"__module__": modpath, "meth": route()(meth)})
        type("B", (a_cls,), {"__module__": modpath})  # extends A, no override

    def test_warning_names_real_defining_class(self):
        from odoo.http import _generate_routing_rules

        self._make_route_less_tree("a1mod")
        with self.assertLogs("odoo.http.routing", level="WARNING") as cm:
            rules = list(_generate_routing_rules(["a1mod"], nodb_only=False))
        msg = "\n".join(cm.output)

        self.assertEqual(rules, [], "a route-less endpoint must yield no rule")
        self.assertIn(
            "odoo.addons.a1mod.controllers.A.meth",
            msg,
            "warning must name the real defining class A",
        )
        self.assertNotIn(
            "(extended by", msg, "must not leak the synthetic merged-controller name"
        )
        self.assertNotIn(
            "odoo.http.routing.A",
            msg,
            "must not report this module as the endpoint's module",
        )


@tagged("post_install", "-at_install")
class TestRequestAppInjection(BaseCase):
    """``Request`` (and ``GeoIP``) take their ``Application`` by injection.

    The serve / session / geoip paths used to reach the ``root`` module
    singleton through ~10 scattered ``from .application import root`` lazy
    imports — ambient global state a test could only steer by monkeypatching
    ``odoo.http.root``. ``Application.__call__`` now injects ``app=self`` and the
    request graph reads ``self.app`` / ``self.request.app`` instead, so a test
    can hand a request its own app with no global patching. The lazy fallback is
    kept for the standalone constructors (``res.device``, tooling), so omitting
    ``app`` must still resolve to the singleton.
    """

    def test_request_stores_injected_app(self):
        from odoo.http import Request

        sentinel = object()
        environ = EnvironBuilder(path="/x").get_environ()
        request = Request(Hwrap.HTTPRequest(environ), app=sentinel)
        self.assertIs(request.app, sentinel)

    def test_geoip_receives_the_same_app(self):
        from odoo.http import Request

        sentinel = object()
        environ = EnvironBuilder(path="/x").get_environ()
        request = Request(Hwrap.HTTPRequest(environ), app=sentinel)
        self.assertIs(
            request.geoip.app,
            sentinel,
            "the request must thread its app into the GeoIP it builds",
        )

    def test_dispatcher_reads_app_via_request(self):
        from odoo.http import Request

        sentinel = object()
        environ = EnvironBuilder(path="/x").get_environ()
        request = Request(Hwrap.HTTPRequest(environ), app=sentinel)
        # ``post_dispatch`` / ``handle_error`` resolve ``root`` as
        # ``self.request.app``; the dispatcher built in __init__ must see it.
        self.assertIs(request.dispatcher.request.app, sentinel)

    def test_no_app_falls_back_to_singleton(self):
        from odoo.http.geoip import GeoIP

        self.assertIs(
            _make_request().app, root, "omitting app must resolve to the singleton"
        )
        self.assertIs(GeoIP("1.2.3.4").app, root)

    def test_explicit_app_is_honoured_by_geoip(self):
        from odoo.http.geoip import GeoIP

        sentinel = object()
        self.assertIs(GeoIP("1.2.3.4", app=sentinel).app, sentinel)

    def test_session_load_uses_injected_store_without_global_patch(self):
        """The headline win: a request resolves its session from the INJECTED
        app's store, so a test never has to monkeypatch
        ``odoo.http.root.session_store``."""
        from unittest.mock import patch

        from odoo.http import Request, request_class

        class FakeApp:
            def __init__(self, store):
                self.session_store = store

        with TemporaryDirectory() as tmp:
            store = FilesystemSessionStore(
                tmp, session_class=Session, renew_missing=True
            )
            seeded = store.new()
            seeded["marker"] = "from-injected-store"
            store.save(seeded)

            environ = EnvironBuilder(
                path="/web", headers={"Cookie": f"session_id={seeded.sid}"}
            ).get_environ()
            request = Request(Hwrap.HTTPRequest(environ), app=FakeApp(store))

            request_class.clear_monodb_cache()
            self.addCleanup(request_class.clear_monodb_cache)
            with (
                patch.object(request_class, "db_list", return_value=[]),
                patch.object(
                    request_class,
                    "db_filter",
                    side_effect=lambda dbs, host=None: list(dbs),
                ),
            ):
                request._post_init()

            self.assertEqual(
                request.session.get("marker"),
                "from-injected-store",
                "session must load from the injected app's store, not the "
                "global root.session_store",
            )


@tagged("post_install", "-at_install")
class TestApplicationCallHelpers(BaseCase):
    """``Application.__call__`` was decomposed into named helpers.

    The WSGI entrypoint used to inline thread-state reset, proxy-fix gating,
    registry-error recovery, exception logging and error-response synthesis in
    one 125-line method — testable only through a full request. Each concern is
    now a method callable in isolation; these lock their contracts directly.
    """

    def test_reset_thread_state_clears_stale_bookkeeping(self):
        """A pooled worker must not report the previous request's bookkeeping."""
        import threading

        # Run on a SEPARATE thread: the helper resets
        # ``threading.current_thread()``, and clobbering the test runner's own
        # thread-locals (it uses them for perf logging) would be unsound.
        result = {}

        def worker():
            t = threading.current_thread()
            t.query_count = 99
            t.query_time = 12
            t.cursor_mode = "ro->rw"
            t.dbname = "stale_db"
            t.uid = 7
            t.url = "http://old/request"
            t.rpc_model_method = "res.users.read"
            root._reset_thread_state()
            result.update(
                query_count=t.query_count,
                query_time=t.query_time,
                cursor_mode=t.cursor_mode,
                rpc=t.rpc_model_method,
                perf_is_float=isinstance(t.perf_t0, float),
                has_dbname=hasattr(t, "dbname"),
                has_uid=hasattr(t, "uid"),
                has_url=hasattr(t, "url"),
            )

        th = threading.Thread(target=worker)
        th.start()
        th.join()

        self.assertEqual(result["query_count"], 0)
        self.assertEqual(result["query_time"], 0)
        self.assertIsNone(result["cursor_mode"])
        self.assertEqual(result["rpc"], "")
        self.assertTrue(result["perf_is_float"])
        # dbname/uid/url are deleted (not zeroed) so a request that fails before
        # repopulating them does not surface stale values.
        self.assertFalse(result["has_dbname"])
        self.assertFalse(result["has_uid"])
        self.assertFalse(result["has_url"])

    def test_apply_proxy_fix_is_gated_on_proxy_mode(self):
        from odoo.tools import config

        def _run(proxy_mode):
            environ = EnvironBuilder(path="/x").get_environ()
            environ["REMOTE_ADDR"] = "10.0.0.1"
            environ["HTTP_X_FORWARDED_FOR"] = "1.2.3.4"
            before = config["proxy_mode"]
            config["proxy_mode"] = proxy_mode
            try:
                root._apply_proxy_fix(environ)
            finally:
                config["proxy_mode"] = before
            return environ["REMOTE_ADDR"]

        self.assertEqual(_run(False), "10.0.0.1", "no rewrite when proxy_mode is off")
        self.assertEqual(
            _run(True),
            "1.2.3.4",
            "trusted X-Forwarded-For must be promoted to REMOTE_ADDR",
        )

    def test_apply_proxy_fix_noop_without_forwarded_headers(self):
        from odoo.tools import config

        environ = EnvironBuilder(path="/x").get_environ()
        environ["REMOTE_ADDR"] = "10.0.0.1"  # no X-Forwarded-* present
        before = config["proxy_mode"]
        config["proxy_mode"] = True
        try:
            root._apply_proxy_fix(environ)
        finally:
            config["proxy_mode"] = before
        self.assertEqual(
            environ["REMOTE_ADDR"],
            "10.0.0.1",
            "proxy_mode on but no forwarded header -> nothing to rewrite",
        )

    def test_ensure_error_response_falls_back_to_500_without_request(self):
        from werkzeug.exceptions import InternalServerError

        exc = RuntimeError("boom")
        root._ensure_error_response(exc, None)
        self.assertIsInstance(exc.error_response, InternalServerError)
        self.assertIn("boom", exc.error_response.description)

    def test_ensure_error_response_empty_message_uses_builtin_description(self):
        # ``str(RuntimeError()) == ""``; the helper passes ``None`` (not "") so
        # werkzeug renders its built-in 500 page, not an empty <p>.
        exc = RuntimeError()
        root._ensure_error_response(exc, None)
        self.assertTrue(
            exc.error_response.description,
            "empty exception message must not blank out the 500 description",
        )

    def test_ensure_error_response_preserves_existing_handler(self):
        exc = RuntimeError("x")
        sentinel = object()
        exc.error_response = sentinel
        root._ensure_error_response(exc, None)
        self.assertIs(
            exc.error_response, sentinel, "an existing error_response must be kept"
        )

    def test_log_request_exception_routes_by_kind(self):
        from werkzeug.exceptions import NotFound

        from odoo.exceptions import UserError

        # Unexpected exception -> ERROR (full traceback).
        with self.assertLogs("odoo.http.application", level="ERROR"):
            root._log_request_exception(RuntimeError("unexpected"))
        # UserError -> WARNING (expected, no traceback).
        with self.assertLogs("odoo.http.application", level="WARNING"):
            root._log_request_exception(UserError("nope"))
        # HTTPException is the controller's deliberate status -> not logged.
        with self.assertNoLogs("odoo.http.application"):
            root._log_request_exception(NotFound())


@tagged("post_install", "-at_install")
class TestRegistryPatchPoint(BaseCase):
    """Lock which ``Registry`` name actually steers the request dispatch path.

    Splitting the monolithic ``http.py`` moved ``Registry(self.db)`` out of the
    ``odoo.http`` namespace and into ``odoo.http._serve`` (with a second binding
    in ``odoo.http.request_class``). A side effect: ``mock.patch`` on the
    historical ``odoo.http.Registry`` re-export — which worked in the monolith
    because one module held both the import and the call site — became a SILENT
    no-op on the dispatch path. The ``odoo.http.Registry`` symbol is kept for
    backward compatibility, but a test that patches it and nothing else mocks
    nothing the request actually uses (e.g. enterprise ``web_mobile``'s multidb
    test passes only because it runs against real databases).

    These assertions pin the contract so the misleading-comment trap cannot
    silently reappear, and so a future maintainer is steered to the effective
    targets ``odoo.http._serve.Registry`` / ``odoo.http.request_class.Registry``.
    """

    def test_http_registry_reexport_is_a_noop_for_dispatch(self):
        from unittest.mock import patch

        import odoo.http as H
        import odoo.http._serve as S
        import odoo.http.request_class as RC

        sentinel = object()
        real = S.Registry
        self.assertIs(
            real,
            RC.Registry,
            "_serve and request_class must share one underlying Registry",
        )
        with patch("odoo.http.Registry", sentinel):
            self.assertIs(H.Registry, sentinel, "patch landed on the re-export")
            self.assertIs(
                S.Registry,
                real,
                "patching odoo.http.Registry must NOT touch the dispatch-path "
                "binding in _serve.py (this is the documented trap)",
            )
            self.assertIs(
                RC.Registry,
                real,
                "patching odoo.http.Registry must NOT touch request_class either",
            )

    def test_serve_registry_is_the_effective_dispatch_patch_point(self):
        from unittest.mock import patch

        import odoo.http._serve as S

        sentinel = object()
        real = S.Registry
        with patch("odoo.http._serve.Registry", sentinel):
            self.assertIs(
                S.Registry,
                sentinel,
                "odoo.http._serve.Registry is the name _serve_db resolves",
            )
        self.assertIs(S.Registry, real, "patch must restore cleanly")


@tagged("post_install", "-at_install")
class TestAcquireRegistryCursor(BaseCase):
    """``_serve_db``'s registry/cursor acquisition is extracted into
    ``_acquire_registry_cursor`` for readability.

    The extraction is only safe if it preserves the cursor-ownership invariant of
    the inlined original: the read-only cursor opened during acquisition MUST be
    closed if acquisition then fails. The original relied on ``_serve_db``'s
    outer ``finally`` for that; the helper now owns it, because on failure the
    cursor never reaches the caller's ``cr`` local. A naive ``return cr``
    extraction leaks the connection — proven, then guarded here for every caught
    failure mode (``ProgrammingError``/``OperationalError``/``AttributeError``).
    """

    class _Cursor:
        def __init__(self):
            self.closed = False
            self.readonly = True

        def close(self):
            self.closed = True

    def _make_db_request(self):
        from odoo.http import Request

        environ = EnvironBuilder(path="/web").get_environ()
        req = Request(Hwrap.HTTPRequest(environ), app=object())
        req.db = "fakedb"
        return req

    def _fake_registry(self, cursor, check_signaling_exc=None):
        from unittest.mock import MagicMock

        reg = MagicMock()
        reg.cursor.return_value = cursor
        if check_signaling_exc is not None:
            reg.check_signaling.side_effect = check_signaling_exc
        else:
            reg.check_signaling.return_value = MagicMock(db_name="fakedb")
        return reg

    def test_cursor_closed_on_each_caught_failure(self):
        from unittest.mock import MagicMock, patch

        import psycopg

        from odoo.http.exceptions import RegistryError

        for exc in (
            psycopg.ProgrammingError("schema broken"),
            psycopg.OperationalError("db gone"),
            AttributeError("registry half-built"),
        ):
            with self.subTest(exc=type(exc).__name__):
                cur = self._Cursor()
                req = self._make_db_request()
                reg = self._fake_registry(cur, check_signaling_exc=exc)
                with (
                    patch("odoo.http._serve.Registry", MagicMock(return_value=reg)),
                    patch("odoo.service.db.list_dbs", return_value=["fakedb"]),
                ):
                    with self.assertRaises(RegistryError):
                        req._acquire_registry_cursor()
                self.assertTrue(
                    cur.closed,
                    f"{type(exc).__name__}: acquisition must close the RO cursor "
                    "it opened — otherwise the connection leaks",
                )

    def test_no_cursor_to_close_when_open_itself_fails(self):
        from unittest.mock import MagicMock, patch

        import psycopg

        from odoo.http.exceptions import RegistryError

        req = self._make_db_request()
        reg = MagicMock()
        reg.cursor.side_effect = psycopg.OperationalError("cannot connect")
        with (
            patch("odoo.http._serve.Registry", MagicMock(return_value=reg)),
            patch("odoo.service.db.list_dbs", return_value=["fakedb"]),
        ):
            # cr stays None; the close-on-failure guard must not crash on None.
            with self.assertRaises(RegistryError):
                req._acquire_registry_cursor()

    def test_returns_open_cursor_on_success(self):
        from unittest.mock import MagicMock, patch

        cur = self._Cursor()
        req = self._make_db_request()
        reg = self._fake_registry(cur)
        with patch("odoo.http._serve.Registry", MagicMock(return_value=reg)):
            got = req._acquire_registry_cursor()
        self.assertIs(got, cur, "the open cursor must transfer to the caller")
        self.assertFalse(cur.closed, "a returned cursor must stay open")
        self.assertIs(
            req.registry,
            reg.check_signaling.return_value,
            "registry must be set from check_signaling",
        )

    def test_serve_db_does_not_leak_cursor_on_registry_failure(self):
        """Integration: the full ``_serve_db`` closes the RO cursor when
        acquisition fails — the leak a naive extraction would reintroduce."""
        from unittest.mock import MagicMock, patch

        import psycopg

        from odoo.http.exceptions import RegistryError

        cur = self._Cursor()
        req = self._make_db_request()
        reg = self._fake_registry(
            cur, check_signaling_exc=psycopg.ProgrammingError("schema broken")
        )
        with (
            patch("odoo.http._serve.Registry", MagicMock(return_value=reg)),
            patch("odoo.service.db.list_dbs", return_value=["fakedb"]),
        ):
            with self.assertRaises(RegistryError):
                req._serve_db()
        self.assertTrue(cur.closed, "_serve_db must not leak the RO cursor")

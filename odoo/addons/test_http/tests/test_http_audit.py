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
  test time instead.
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

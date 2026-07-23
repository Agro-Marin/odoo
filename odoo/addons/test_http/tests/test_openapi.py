"""OpenAPI generation from the routing map (built on typed routing).

``TestOpenApi`` unit-tests the pure generator (:mod:`odoo.http.openapi`);
``TestOpenApiEndpoint`` fetches the served ``/test_http/openapi.json`` and checks
the typed route is documented with its coerced parameter schema.
"""

from odoo.http._params import ParamSpec
from odoo.http.openapi import (
    RouteInfo,
    build_openapi,
    openapi_from_map,
    param_spec_to_schema,
)
from odoo.tests import BaseCase, HttpCase, new_test_user, tagged

from odoo.addons.test_http.tests.test_common import TestHttpBase


def _http_handler(self, n: int, flag: bool = False, **kw):
    """Echo n and flag."""
    return


def _json_handler(self, qty: int, note: str | None = None, **kw):
    return None


@tagged("post_install", "-at_install")
class TestOpenApi(BaseCase):
    """Pure unit tests of the OpenAPI generator."""

    def test_param_spec_to_schema(self):
        self.assertEqual(
            param_spec_to_schema(ParamSpec(int, None, False, True)), {"type": "integer"}
        )
        self.assertEqual(
            param_spec_to_schema(ParamSpec(str, None, True, False)),
            {"type": ["string", "null"]},
        )
        self.assertEqual(
            param_spec_to_schema(ParamSpec(list, int, False, False)),
            {"type": "array", "items": {"type": "integer"}},
        )

    def test_http_typed_route_documents_query_params_and_path_params(self):
        route = RouteInfo(
            "/x/<int:id>",
            frozenset({"GET", "HEAD"}),
            {"type": "http", "auth": "public", "typed": True},
            _http_handler,
        )
        doc = build_openapi([route])
        self.assertEqual(doc["openapi"], "3.1.0")
        path_item = doc["paths"]["/x/{id}"]
        self.assertNotIn("head", path_item)  # implicit verb omitted
        op = path_item["get"]
        params = {(p["name"], p["in"]): p for p in op["parameters"]}
        self.assertEqual(params[("id", "path")]["schema"], {"type": "integer"})
        self.assertTrue(params[("n", "query")]["required"])
        self.assertEqual(params[("flag", "query")]["schema"], {"type": "boolean"})
        self.assertEqual(op["security"], [])  # public
        self.assertIn("400", op["responses"])
        self.assertEqual(op["summary"], "Echo n and flag.")

    def test_jsonrpc_typed_route_uses_request_body_and_security(self):
        route = RouteInfo(
            "/api/order",
            frozenset({"POST"}),
            {"type": "jsonrpc", "auth": "user", "typed": True},
            _json_handler,
        )
        doc = build_openapi([route])
        op = doc["paths"]["/api/order"]["post"]
        schema = op["requestBody"]["content"]["application/json"]["schema"]
        self.assertEqual(schema["properties"]["qty"], {"type": "integer"})
        self.assertEqual(schema["properties"]["note"], {"type": ["string", "null"]})
        self.assertEqual(schema["required"], ["qty"])
        self.assertEqual(op["security"], [{"sessionCookie": []}])
        self.assertEqual(
            doc["components"]["securitySchemes"]["sessionCookie"]["in"], "cookie"
        )

    def test_operation_ids_are_document_unique(self):
        # Two controllers reusing a handler name (``index``) must not collide:
        # operationIds derive from (method, path), unique by construction.
        def index(self, **kw):
            return None

        routes = [
            RouteInfo("/shop", frozenset({"GET", "POST"}), {"type": "http"}, index),
            RouteInfo("/blog", frozenset({"GET"}), {"type": "http"}, index),
            RouteInfo("/x/<int:id>", frozenset({"GET"}), {"type": "http"}, index),
        ]
        doc = build_openapi(routes)
        ids = [
            op["operationId"] for item in doc["paths"].values() for op in item.values()
        ]
        self.assertEqual(len(ids), len(set(ids)), f"duplicate operationIds: {ids}")
        self.assertEqual(doc["paths"]["/shop"]["get"]["operationId"], "get_shop")
        self.assertEqual(doc["paths"]["/x/{id}"]["get"]["operationId"], "get_x_id")

    def test_typed_only_filters_untyped_routes(self):
        typed = RouteInfo(
            "/typed", frozenset({"GET"}), {"type": "http", "typed": True}, _http_handler
        )
        untyped = RouteInfo(
            "/legacy", frozenset({"GET"}), {"type": "http"}, lambda self, **k: None
        )
        doc = build_openapi([typed, untyped], typed_only=True)
        self.assertIn("/typed", doc["paths"])
        self.assertNotIn("/legacy", doc["paths"])

    def test_openapi_from_map(self):
        def handler(self, n: int, **kw):
            return None

        handler.routing = {"type": "http", "auth": "public", "typed": True}
        handler.original_endpoint = handler
        import werkzeug.routing as wz

        wmap = wz.Map([wz.Rule("/a/<int:id>", endpoint=handler, methods=["GET"])])
        op = openapi_from_map(wmap, title="T", version="9")["paths"]["/a/{id}"]["get"]
        self.assertEqual(
            {(p["name"], p["in"]) for p in op["parameters"]},
            {("id", "path"), ("n", "query")},
        )


@tagged("post_install", "-at_install")
class TestOpenApiEndpoint(TestHttpBase):
    """End-to-end: the served /openapi.json documents the live typed route."""

    def test_endpoint_documents_typed_echo(self):
        res = self.nodb_url_open("/test_http/openapi.json")
        self.assertEqual(res.status_code, 200)
        spec = res.json()
        self.assertEqual(spec["openapi"], "3.1.0")
        op = spec["paths"]["/test_http/typed-echo"]["get"]
        params = {(p["name"], p["in"]): p for p in op["parameters"]}
        self.assertEqual(params[("n", "query")]["schema"], {"type": "integer"})
        self.assertTrue(params[("n", "query")]["required"])
        self.assertEqual(params[("flag", "query")]["schema"], {"type": "boolean"})

    def test_endpoint_omits_untyped_routes(self):
        spec = self.nodb_url_open("/test_http/openapi.json").json()
        # echo-http-get is auth='none' but not typed -> excluded by typed_only
        self.assertNotIn("/test_http/echo-http-get", spec["paths"])


@tagged("post_install", "-at_install")
class TestWebOpenApiEndpoint(HttpCase):
    """The production ``/web/openapi.json`` (web module): generated from the
    DATABASE routing map, gated to system administrators."""

    def test_admin_gets_document_with_db_typed_routes(self):
        self.authenticate("admin", "admin")
        res = self.url_open("/web/openapi.json")
        self.assertEqual(res.status_code, 200)
        spec = res.json()
        self.assertEqual(spec["openapi"], "3.1.0")
        # Generated from the db map: test_http's typed route is documented,
        # untyped routes are not (typed_only is not optional on this endpoint).
        self.assertIn("/test_http/typed-echo", spec["paths"])
        self.assertNotIn("/test_http/echo-http-get", spec["paths"])
        self.assertEqual(spec["servers"], [{"url": self.base_url()}])

    def test_non_admin_is_forbidden(self):
        new_test_user(
            self.env,
            login="openapi_internal",
            password="openapi_internal+1",
            groups="base.group_user",
        )
        self.authenticate("openapi_internal", "openapi_internal+1")
        res = self.url_open("/web/openapi.json")
        self.assertEqual(res.status_code, 403)

    def test_anonymous_is_redirected_to_login(self):
        self.authenticate(None, None)
        res = self.url_open("/web/openapi.json", allow_redirects=False)
        self.assertEqual(res.status_code, 303)
        self.assertIn("/web/login", res.headers.get("Location", ""))

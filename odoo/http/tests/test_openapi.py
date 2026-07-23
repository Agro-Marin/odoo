"""DB-free unit tests for OpenAPI generation from routing descriptors.

:mod:`odoo.http.openapi` takes plain :class:`RouteInfo` descriptors, so the whole
document generator is testable without a registry or werkzeug map. Run in the
tier-2 (real-import) invocation, e.g. ``pytest odoo/http/tests``.
"""

import werkzeug.routing

from odoo.http.openapi import (
    RouteInfo,
    _effective_methods,
    _operation_id,
    build_openapi,
    openapi_from_map,
)


def _route(rule, *, methods=frozenset(), routing=None, handler=None):
    return RouteInfo(
        rule=rule,
        methods=frozenset(methods),
        routing=routing or {"type": "http", "auth": "public"},
        handler=handler or (lambda self: None),
    )


def test_effective_methods_defaults_when_no_allow_list():
    # Regression: a route with no explicit ``methods`` must still document verbs.
    http_route = _route("/v", methods=frozenset(), routing={"type": "http"})
    assert _effective_methods(http_route) == frozenset({"GET", "POST"})
    rpc_route = _route("/rpc", methods=frozenset(), routing={"type": "jsonrpc"})
    assert _effective_methods(rpc_route) == frozenset({"POST"})


def test_effective_methods_strips_implicit_verbs():
    r = _route("/v", methods=frozenset({"GET", "HEAD", "OPTIONS"}))
    assert _effective_methods(r) == frozenset({"GET"})
    # a route left with only implicit verbs falls back to the default.
    only_implicit = _route("/v", methods=frozenset({"HEAD", "OPTIONS"}))
    assert _effective_methods(only_implicit) == frozenset({"GET", "POST"})


def test_methods_none_route_emits_operations():
    """Regression: methods=None used to produce an empty ``{}`` path item."""
    doc = build_openapi([_route("/web/version", methods=frozenset())])
    assert sorted(doc["paths"]["/web/version"]) == ["get", "post"]


def test_operation_id_disambiguates_realistic_collision():
    """Regression: ``/shop/cart`` and ``/shop-cart`` both slug to ``shop_cart``."""
    used = set()
    first = _operation_id("GET", "/shop/cart", used)
    second = _operation_id("GET", "/shop-cart", used)
    assert first == "get_shop_cart"
    assert second == "get_shop_cart_2"
    assert first != second


def test_build_openapi_no_duplicate_operation_ids():
    doc = build_openapi(
        [
            _route("/shop/cart", methods=frozenset({"GET"})),
            _route("/shop-cart", methods=frozenset({"GET"})),
        ]
    )
    ids = [op["operationId"] for path in doc["paths"].values() for op in path.values()]
    assert len(ids) == len(set(ids)) == 2


def test_typed_route_documents_query_params_and_400():
    def handler(self, n: int, flag: bool = False):
        """List things."""

    route = _route(
        "/typed",
        methods=frozenset({"GET"}),
        routing={"type": "http", "auth": "public", "typed": True},
        handler=handler,
    )
    op = build_openapi([route])["paths"]["/typed"]["get"]
    assert op["summary"] == "List things."
    names = {p["name"]: p for p in op["parameters"]}
    assert names["n"]["required"] is True
    assert names["n"]["schema"] == {"type": "integer"}
    assert names["flag"]["required"] is False
    assert "400" in op["responses"]


def test_typed_jsonrpc_documents_request_body():
    def handler(self, n: int): ...

    route = _route(
        "/rpc",
        methods=frozenset({"POST"}),
        routing={"type": "jsonrpc", "auth": "user", "typed": True},
        handler=handler,
    )
    op = build_openapi([route])["paths"]["/rpc"]["post"]
    body = op["requestBody"]["content"]["application/json"]["schema"]
    assert body["properties"]["n"] == {"type": "integer"}
    assert body["required"] == ["n"]


def test_path_param_not_duplicated_as_query_param():
    """Regression: a path param that is ALSO annotated on the handler (the usual
    way to coerce it) was emitted twice — once ``in: path``, once a spurious
    ``in: query`` telling clients to pass a URL value in the query string."""

    def handler(self, ident: int, q: str | None = None):
        """Get item."""

    route = _route(
        "/item/<int:ident>",
        methods=frozenset({"GET"}),
        routing={"type": "http", "auth": "public", "typed": True},
        handler=handler,
    )
    op = build_openapi([route])["paths"]["/item/{ident}"]["get"]
    ident_params = [p for p in op["parameters"] if p["name"] == "ident"]
    assert len(ident_params) == 1
    assert ident_params[0]["in"] == "path"
    # the genuine query param still shows up
    assert {p["name"] for p in op["parameters"]} == {"ident", "q"}


def test_path_param_not_duplicated_in_request_body():
    """Same leak on the body side: a json2/jsonrpc path param must not appear as
    a request-body property — it comes from the URL, not the JSON payload."""

    def handler(self, ident: int, name: str):
        """Create."""

    route = _route(
        "/item/<int:ident>",
        methods=frozenset({"POST"}),
        routing={"type": "json2", "auth": "bearer", "typed": True},
        handler=handler,
    )
    op = build_openapi([route])["paths"]["/item/{ident}"]["post"]
    body = op["requestBody"]["content"]["application/json"]["schema"]
    assert set(body["properties"]) == {"name"}  # ident excluded
    assert body["required"] == ["name"]
    assert [p["name"] for p in op["parameters"] if p["in"] == "path"] == ["ident"]


def test_typed_only_filters_untyped_routes():
    typed = _route(
        "/typed",
        methods=frozenset({"GET"}),
        routing={"type": "http", "auth": "public", "typed": True},
    )
    untyped = _route("/plain", methods=frozenset({"GET"}))
    doc = build_openapi([typed, untyped], typed_only=True)
    assert set(doc["paths"]) == {"/typed"}


def test_security_schemes_registered_per_auth():
    bearer = _route(
        "/b", methods=frozenset({"GET"}), routing={"type": "http", "auth": "bearer"}
    )
    doc = build_openapi([bearer])
    assert "bearerAuth" in doc["components"]["securitySchemes"]
    assert doc["paths"]["/b"]["get"]["security"] == [{"bearerAuth": []}]


def test_openapi_from_map_roundtrip():
    m = werkzeug.routing.Map()

    def handler(self, ident): ...

    handler.routing = {"type": "http", "auth": "public"}
    handler.original_endpoint = handler
    m.add(werkzeug.routing.Rule("/a/<int:ident>", endpoint=handler, methods=["GET"]))
    doc = openapi_from_map(m, title="T", version="9")
    op = doc["paths"]["/a/{ident}"]["get"]
    assert doc["info"] == {"title": "T", "version": "9"}
    assert op["parameters"][0]["schema"] == {"type": "integer"}

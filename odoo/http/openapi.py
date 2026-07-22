"""Generate an OpenAPI 3.1 document from the HTTP routing map.

Each route contributes a path item built from its frozen ``endpoint.routing``
(path, methods, auth, type) and — for ``@route(typed=True)`` routes — a request
schema derived from the handler's annotations (see :mod:`odoo.http._params`):
query parameters for ``type='http'``, a JSON request body for ``jsonrpc`` /
``json2``. Untyped routes are listed with their path parameters only, because
their request parameters carry no enforced type to document honestly.

The generator core takes plain :class:`RouteInfo` descriptors, so it is
unit-testable without a registry or a database; :func:`openapi_from_map` adapts a
built werkzeug :class:`~werkzeug.routing.Map` into those descriptors.
"""

from __future__ import annotations

import re
import typing
from typing import Any, NamedTuple

from ._params import ParamSpec, build_param_specs

OPENAPI_VERSION = "3.1.0"

# Maps a werkzeug path converter to a JSON Schema type; anything not listed
# (string/default, path, any, uuid) documents as a plain string.
_CONVERTER_SCHEMA: dict[str, dict[str, str]] = {
    "int": {"type": "integer"},
    "float": {"type": "number"},
}

_PRIMITIVE_SCHEMA: dict[type, dict[str, str]] = {
    int: {"type": "integer"},
    float: {"type": "number"},
    bool: {"type": "boolean"},
    str: {"type": "string"},
}

# ``<int:id>`` / ``<id>`` / ``<any(a,b):x>`` -> converter (optional) + name.
_RULE_ARG_RE = re.compile(
    r"<(?:(?P<conv>[a-zA-Z_]\w*)(?:\([^>]*\))?:)?(?P<name>[a-zA-Z_]\w*)>"
)

# HTTP verbs werkzeug adds implicitly; not emitted as OpenAPI operations.
_IMPLICIT_METHODS = frozenset({"HEAD", "OPTIONS"})

# When a route declares no ``methods`` allow-list, werkzeug lets it match every
# verb. The framework's own default for that case (``Dispatcher.pre_dispatch``'s
# CORS ``Access-Control-Allow-Methods``) is POST for ``jsonrpc`` and GET+POST
# otherwise; mirror it here so the document and the runtime can't drift and an
# unrestricted route is no longer emitted with zero operations.
_DEFAULT_METHODS_JSONRPC = frozenset({"POST"})
_DEFAULT_METHODS_OTHER = frozenset({"GET", "POST"})


def _effective_methods(route: RouteInfo) -> frozenset[str]:
    """The verbs to document for ``route``, applying the no-allow-list default."""
    real = route.methods - _IMPLICIT_METHODS
    if real:
        return real
    if route.routing.get("type") == "jsonrpc":
        return _DEFAULT_METHODS_JSONRPC
    return _DEFAULT_METHODS_OTHER


# Characters not allowed in an operationId slug (collapsed to ``_``).
_ID_SANITIZE_RE = re.compile(r"[^a-zA-Z0-9]+")


def _operation_id(method: str, template: str, used: set[str] | None = None) -> str:
    """Build a document-unique operationId from the method and path template.

    OpenAPI requires operationIds to be unique across the document. Deriving the
    id from the handler ``__name__`` (the previous scheme) collides as soon as two
    controllers reuse a method name (two ``index`` handlers → two ``index_get``).

    ``(method, path)`` is *nearly* unique, but the slug sanitizer collapses every
    non-alphanumeric run to ``_``, so distinct templates that differ only in their
    separators still clash (``/shop/cart`` and ``/shop-cart`` both → ``shop_cart``).
    When ``used`` is supplied, a clash is broken deterministically with a numeric
    suffix (``…_2``, ``…_3``); the chosen id is recorded in ``used``. The order is
    the caller's iteration order over the routing map, which is stable for a
    deployment, so ids stay stable across regenerations.
    """
    slug = _ID_SANITIZE_RE.sub("_", template).strip("_") or "root"
    base = f"{method.lower()}_{slug}"
    if used is None:
        return base
    candidate = base
    suffix = 2
    while candidate in used:
        candidate = f"{base}_{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


class RouteInfo(NamedTuple):
    """One route, normalised for OpenAPI generation.

    :param rule: the werkzeug path template (e.g. ``/shop/<int:id>``).
    :param methods: the HTTP verbs the route serves.
    :param routing: the frozen ``endpoint.routing`` mapping (auth, type, typed…).
    :param handler: the underlying handler (``endpoint.original_endpoint``) whose
        annotations describe the request when ``routing['typed']`` is set.
    """

    rule: str
    methods: frozenset[str]
    routing: typing.Mapping[str, Any]
    handler: typing.Callable


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    """Make a JSON Schema accept ``null`` (OpenAPI 3.1 type-union form)."""
    kind = schema.get("type")
    if isinstance(kind, str):
        return {**schema, "type": [kind, "null"]}
    return schema


def param_spec_to_schema(spec: ParamSpec) -> dict[str, Any]:
    """Translate a :class:`ParamSpec` into a JSON Schema object."""
    if spec.target is list:
        item = _PRIMITIVE_SCHEMA.get(spec.item) if spec.item else None
        schema: dict[str, Any] = {"type": "array", "items": dict(item) if item else {}}
    else:
        schema = dict(_PRIMITIVE_SCHEMA.get(spec.target, {}))
    return _nullable(schema) if spec.allow_none else schema


def _path_template(rule: str) -> tuple[str, list[dict[str, Any]]]:
    """Convert a werkzeug rule to an OpenAPI path + its path-parameter objects."""
    params: list[dict[str, Any]] = []

    def repl(match: re.Match[str]) -> str:
        name = match.group("name")
        conv = match.group("conv") or "default"
        schema = _CONVERTER_SCHEMA.get(conv, {"type": "string"})
        params.append(
            {"name": name, "in": "path", "required": True, "schema": dict(schema)}
        )
        return "{" + name + "}"

    return _RULE_ARG_RE.sub(repl, rule), params


# auth value -> (security-scheme name, scheme definition)
_SECURITY_SCHEMES: dict[str, tuple[str, dict[str, str]]] = {
    "bearer": ("bearerAuth", {"type": "http", "scheme": "bearer"}),
    "user": ("sessionCookie", {"type": "apiKey", "in": "cookie", "name": "session_id"}),
}


def _summary(handler: typing.Callable) -> str | None:
    doc = getattr(handler, "__doc__", None)
    return doc.strip().splitlines()[0] if doc and doc.strip() else None


def build_operation(
    route: RouteInfo,
    method: str,
    template: str,
    path_params: list[dict[str, Any]],
    security_schemes: dict[str, dict[str, str]],
    used_operation_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Build one OpenAPI operation object for ``route`` served via ``method``.

    ``template`` is the OpenAPI path (from :func:`_path_template`); with
    ``method`` it forms the document-unique ``operationId`` (disambiguated against
    ``used_operation_ids`` when supplied). Registers any security scheme it uses
    into ``security_schemes`` (mutated).
    """
    operation: dict[str, Any] = {
        "operationId": _operation_id(method, template, used_operation_ids),
        "responses": {"200": {"description": "Successful response"}},
    }
    if summary := _summary(route.handler):
        operation["summary"] = summary

    parameters = list(path_params)
    route_type = route.routing.get("type", "http")
    if route.routing.get("typed"):
        specs = build_param_specs(route.handler)
        if route_type == "http":
            parameters += [
                {
                    "name": name,
                    "in": "query",
                    "required": spec.required,
                    "schema": param_spec_to_schema(spec),
                }
                for name, spec in specs.items()
            ]
        elif specs:
            required = [name for name, spec in specs.items() if spec.required]
            body: dict[str, Any] = {
                "type": "object",
                "properties": {n: param_spec_to_schema(s) for n, s in specs.items()},
            }
            if required:
                body["required"] = required
            operation["requestBody"] = {
                "content": {"application/json": {"schema": body}}
            }
        operation["responses"]["400"] = {"description": "Invalid request parameters"}

    if parameters:
        operation["parameters"] = parameters

    auth = route.routing.get("auth")
    if auth in _SECURITY_SCHEMES:
        name, definition = _SECURITY_SCHEMES[auth]
        security_schemes[name] = definition
        operation["security"] = [{name: []}]
    elif auth in ("public", "none"):
        operation["security"] = []  # explicitly unauthenticated

    return operation


def build_openapi(
    routes: typing.Iterable[RouteInfo],
    *,
    title: str = "Odoo HTTP API",
    version: str = "19.0",
    servers: list[dict[str, Any]] | None = None,
    typed_only: bool = False,
) -> dict[str, Any]:
    """Assemble an OpenAPI 3.1 document from ``routes``.

    Routes sharing a path are merged into one path item keyed by HTTP method;
    implicit ``HEAD``/``OPTIONS`` verbs are omitted. With ``typed_only=True``,
    only ``@route(typed=True)`` routes are emitted — the curated, schema-bearing
    API — so the document never leaks the full internal route surface.
    """
    paths: dict[str, dict[str, Any]] = {}
    security_schemes: dict[str, dict[str, str]] = {}
    used_operation_ids: set[str] = set()

    for route in routes:
        if typed_only and not route.routing.get("typed"):
            continue
        template, path_params = _path_template(route.rule)
        path_item = paths.setdefault(template, {})
        for method in sorted(_effective_methods(route)):
            path_item[method.lower()] = build_operation(
                route,
                method,
                template,
                path_params,
                security_schemes,
                used_operation_ids,
            )

    document: dict[str, Any] = {
        "openapi": OPENAPI_VERSION,
        "info": {"title": title, "version": version},
        "paths": paths,
    }
    if servers:
        document["servers"] = servers
    if security_schemes:
        document["components"] = {"securitySchemes": security_schemes}
    return document


def iter_map_routes(routing_map: Any) -> typing.Iterator[RouteInfo]:
    """Adapt a werkzeug :class:`~werkzeug.routing.Map` into :class:`RouteInfo`\\ s."""
    for rule in routing_map.iter_rules():
        endpoint = rule.endpoint
        routing = getattr(endpoint, "routing", {})
        handler = getattr(endpoint, "original_endpoint", endpoint)
        yield RouteInfo(
            rule=rule.rule,
            methods=frozenset(rule.methods or ()),
            routing=routing,
            handler=handler,
        )


def openapi_from_map(routing_map: Any, **kwargs: Any) -> dict[str, Any]:
    """Build an OpenAPI document from a built werkzeug routing ``Map``."""
    return build_openapi(iter_map_routes(routing_map), **kwargs)

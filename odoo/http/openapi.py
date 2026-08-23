from __future__ import annotations

import logging
import re
import typing
from typing import Any, NamedTuple

from ._params import ParamSpec, build_param_specs

_logger = logging.getLogger(__name__)

OPENAPI_VERSION = "3.1.0"

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

_RULE_ARG_RE = re.compile(
    r"<(?:(?P<conv>[a-zA-Z_]\w*)(?:\([^>]*\))?:)?(?P<name>[a-zA-Z_]\w*)>"
)

_IMPLICIT_METHODS = frozenset({"HEAD", "OPTIONS"})

_DEFAULT_METHODS_JSONRPC = frozenset({"POST"})
_DEFAULT_METHODS_OTHER = frozenset({"GET", "POST"})


def _effective_methods(route: RouteInfo) -> frozenset[str]:
    real = route.methods - _IMPLICIT_METHODS
    if real:
        return real
    if route.routing.get("type") == "jsonrpc":
        return _DEFAULT_METHODS_JSONRPC
    return _DEFAULT_METHODS_OTHER


_ID_SANITIZE_RE = re.compile(r"[^a-zA-Z0-9]+")


def _operation_id(method: str, template: str, used: set[str] | None = None) -> str:
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
    rule: str
    methods: frozenset[str]
    routing: typing.Mapping[str, Any]
    handler: typing.Callable


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    kind = schema.get("type")
    if isinstance(kind, str):
        return {**schema, "type": [kind, "null"]}
    return schema


def param_spec_to_schema(spec: ParamSpec) -> dict[str, Any]:
    if spec.target is list:
        item = _PRIMITIVE_SCHEMA.get(spec.item) if spec.item else None
        schema: dict[str, Any] = {"type": "array", "items": dict(item) if item else {}}
    else:
        schema = dict(_PRIMITIVE_SCHEMA.get(spec.target, {}))
    return _nullable(schema) if spec.allow_none else schema


def _path_template(rule: str) -> tuple[str, list[dict[str, Any]]]:
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
    operation: dict[str, Any] = {
        "operationId": _operation_id(method, template, used_operation_ids),
        "responses": {"200": {"description": "Successful response"}},
    }
    if summary := _summary(route.handler):
        operation["summary"] = summary

    parameters = list(path_params)
    route_type = route.routing.get("type", "http")
    if route.routing.get("typed"):
        path_param_names = {p["name"] for p in path_params}
        specs = {
            name: spec
            for name, spec in build_param_specs(route.handler).items()
            if name not in path_param_names
        }
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
        operation["security"] = []

    return operation


def build_openapi(
    routes: typing.Iterable[RouteInfo],
    *,
    title: str = "Odoo HTTP API",
    version: str = "19.0",
    servers: list[dict[str, Any]] | None = None,
    typed_only: bool = False,
) -> dict[str, Any]:
    paths: dict[str, dict[str, Any]] = {}
    security_schemes: dict[str, dict[str, str]] = {}
    used_operation_ids: set[str] = set()

    claimed_by: dict[tuple[str, str], str] = {}

    for route in routes:
        if typed_only and not route.routing.get("typed"):
            continue
        template, path_params = _path_template(route.rule)
        path_item = paths.setdefault(template, {})
        for method in sorted(_effective_methods(route)):
            verb = method.lower()
            if verb in path_item:
                _logger.warning(
                    "OpenAPI: %s %s is already described by %r; %r renders to "
                    "the same path template and cannot be documented too.",
                    method,
                    template,
                    claimed_by.get((template, verb)),
                    route.rule,
                )
                continue
            claimed_by[template, verb] = route.rule
            path_item[verb] = build_operation(
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
    return build_openapi(iter_map_routes(routing_map), **kwargs)

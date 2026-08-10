from __future__ import annotations

import annotationlib
import functools
import inspect
import logging
import warnings
from collections.abc import Callable, Generator, Iterable
from types import MappingProxyType
from typing import Any

import werkzeug.routing

from odoo.tools import unique
from odoo.tools.misc import submap

from ._params import build_param_specs
from .constants import ROUTING_KEYS
from .controller import Controller
from .core import request
from .dispatcher import _dispatchers
from .wrappers import Response

_logger = logging.getLogger(__name__)

_KNOWN_ROUTING_PARAMETERS: set[str] = {
    "auth",
    "captcha",
    "cors",
    "cors_credentials",
    "csrf",
    "handle_params_access_error",
    "max_content_length",
    "readonly",
    "save_session",
    "type",
    "typed",
    *ROUTING_KEYS,
    "website",
    "multilang",
    "sitemap",
    "list_as_website_content",
}


def register_routing_parameters(*names: str) -> None:
    _KNOWN_ROUTING_PARAMETERS.update(names)


class LazyCompiledBuilder:
    def __init__(
        self,
        rule: werkzeug.routing.Rule,
        _compile_builder: Any,
        append_unknown: bool,
    ) -> None:
        self.rule = rule
        self._callable = None
        self._compile_builder = _compile_builder
        self._append_unknown = append_unknown

    def __get__(self, *args: Any) -> LazyCompiledBuilder:
        return self

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        fn = self._callable
        if fn is None:
            fn = self._compile_builder(self._append_unknown).__get__(self.rule, None)
            self._callable = fn
        return fn(*args, **kwargs)


class FasterRule(werkzeug.routing.Rule):
    def _compile_builder(self, append_unknown: bool = True) -> LazyCompiledBuilder:
        return LazyCompiledBuilder(self, super()._compile_builder, append_unknown)


def rule_routing_kwargs(endpoint: Callable) -> dict[str, Any]:
    routing = submap(endpoint.routing, ROUTING_KEYS)
    methods = routing.get("methods")
    if methods is not None and "OPTIONS" not in methods:
        routing["methods"] = [*methods, "OPTIONS"]
    return routing


def _route_param_filter(endpoint: Callable) -> tuple[bool, frozenset[str], str]:
    accepts_var_keyword = False
    named: set[str] = set()
    params = list(
        inspect.signature(
            endpoint, annotation_format=annotationlib.Format.FORWARDREF
        ).parameters.values()
    )
    bound_self_name = params[0].name if params else "self"
    for param in params[1:]:
        if param.kind is inspect.Parameter.VAR_KEYWORD:
            accepts_var_keyword = True
        elif param.kind in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        ):
            named.add(param.name)
    return accepts_var_keyword, frozenset(named), bound_self_name


def _apply_param_specs(endpoint: Callable, specs: dict[str, Any] | None) -> None:
    endpoint._param_specs = specs
    endpoint.typed_list_params = (
        frozenset(name for name, spec in specs.items() if spec.target is list)
        if specs
        else None
    )


def _original_endpoint(method: Any) -> Callable:
    return method.original_endpoint


def _reject_wildcard_credentials(who: str, routing: Any) -> None:
    if routing.get("cors") == "*" and routing.get("cors_credentials"):
        e = (
            f"{who}: cors='*' cannot be combined with cors_credentials. Name the "
            "allowed origin explicitly, or pass a resolver callable such as "
            "odoo.http.cors_same_host."
        )
        raise ValueError(e)


def _effective_route_type(declared_routing: dict[str, Any]) -> str:
    declared = declared_routing.get("type")
    if declared is not None:
        return declared
    if request:
        return request.dispatcher.routing_type
    return "http"


def route(route: str | Iterable[str] | None = None, **routing: Any) -> Callable:

    def decorator(endpoint: Callable) -> Callable:
        fname = f"<function {endpoint.__module__}.{endpoint.__name__}>"

        if routing.get("type") == "json":
            warnings.warn(
                "Since 19.0, @route(type='json') is a deprecated alias to @route(type='jsonrpc')",
                DeprecationWarning,
                stacklevel=2,
            )
            routing["type"] = "jsonrpc"
        route_type = routing.get("type", "http")
        if route_type not in _dispatchers:
            raise ValueError(
                f"@route(type={route_type!r}) is not one of {list(_dispatchers)}"
            )
        if route:
            routing["routes"] = [route] if isinstance(route, str) else list(route)
        wrong = routing.pop("method", None)
        if wrong is not None:
            _logger.warning(
                "%s defined with invalid routing parameter 'method', assuming 'methods'",
                fname,
            )
            routing["methods"] = wrong
        _reject_wildcard_credentials(fname, routing)
        unknown = routing.keys() - _KNOWN_ROUTING_PARAMETERS - {"routes"}
        if unknown:
            _logger.warning(
                "%s defined with unknown @route parameter(s) %s; they are kept "
                "in endpoint.routing, but no module declared them via "
                "odoo.http.register_routing_parameters() — possible typo.",
                fname,
                sorted(unknown),
            )

        accepts_var_keyword, accepted_params, bound_self_name = _route_param_filter(
            endpoint
        )

        @functools.wraps(endpoint)
        def route_wrapper(controller_self, /, *args, **params):
            if accepts_var_keyword:
                params_ok = params
                params_ko = None
                if bound_self_name in params:
                    params_ok = {
                        k: v for k, v in params.items() if k != bound_self_name
                    }
                    params_ko = {bound_self_name}
            elif params.keys() <= accepted_params:
                params_ok = params
                params_ko = None
            else:
                params_ok = {k: v for k, v in params.items() if k in accepted_params}
                params_ko = params.keys() - accepted_params
            if params_ko:
                _logger.warning("%s called ignoring args %s", fname, params_ko)

            result = endpoint(controller_self, *args, **params_ok)
            if _effective_route_type(routing) == "http":
                return Response.load(result, fname)
            return result

        route_wrapper.original_routing = routing
        route_wrapper.original_endpoint = endpoint
        return route_wrapper

    return decorator


def _generate_routing_rules(
    modules: list[str], nodb_only: bool
) -> Generator[tuple[str, Any]]:

    def is_valid(cls: type) -> bool:
        path = cls.__module__.split(".")
        return path[:2] == ["odoo", "addons"] and path[2] in modules

    def get_leaf_classes(cls: type) -> list[type]:
        result = []
        for subcls in cls.__subclasses__():
            if is_valid(subcls):
                result.extend(get_leaf_classes(subcls))
        if not result and is_valid(cls):
            result.append(cls)
        return result

    def build_controllers() -> Generator[Controller]:
        yield from (ctrl() for ctrl in Controller.children_classes.get("", []))

        highest_controllers = []
        for module in modules:
            highest_controllers.extend(Controller.children_classes.get(module, []))

        for top_ctrl in highest_controllers:
            leaf_controllers = list(unique(get_leaf_classes(top_ctrl)))

            name = top_ctrl.__name__
            if leaf_controllers != [top_ctrl]:
                extended_by = ", ".join(
                    bot_ctrl.__name__
                    for bot_ctrl in leaf_controllers
                    if bot_ctrl is not top_ctrl
                )
                name += f" (extended by {extended_by})"

            Ctrl = type(name, tuple(reversed(leaf_controllers)), {})
            yield Ctrl()

    for ctrl in build_controllers():
        for method_name, method in inspect.getmembers(ctrl, inspect.ismethod):

            def is_method_a_route(cls: type, method_name: str = method_name) -> bool:
                return (
                    getattr(
                        getattr(cls, method_name, None),
                        "original_routing",
                        None,
                    )
                    is not None
                )

            if not any(map(is_method_a_route, type(ctrl).mro())):
                continue

            merged_routing = {
                "auth": "user",
                "methods": None,
                "routes": [],
            }

            ancestors = [
                cls
                for cls in reversed(type(ctrl).mro())
                if cls is not Controller and cls is not object
            ]
            defining_cls = None
            for cls in unique(ancestors):
                if method_name not in cls.__dict__:
                    continue
                submethod = getattr(cls, method_name)

                if not hasattr(submethod, "original_routing"):
                    _logger.warning(
                        "The endpoint %s is overridden without @route(); skipping this override.",
                        f"{cls.__module__}.{cls.__name__}.{method_name}",
                    )
                    continue

                defining_cls = cls

                merged_routing.update(
                    _check_and_complete_route_definition(cls, submethod, merged_routing)
                )

            if not merged_routing["routes"]:
                owner = defining_cls if defining_cls is not None else type(ctrl)
                _logger.warning(
                    "%s is a controller endpoint without any route, skipping.",
                    f"{owner.__module__}.{owner.__name__}.{method_name}",
                )
                continue

            if nodb_only and merged_routing["auth"] != "none":
                continue

            _reject_wildcard_credentials(
                f"{type(ctrl).__name__}.{method_name}", merged_routing
            )

            merged_routing.setdefault(
                "save_session", merged_routing["auth"] != "bearer"
            )

            if isinstance(merged_routing.get("methods"), list):
                merged_routing["methods"] = tuple(merged_routing["methods"])
            frozen_routing = MappingProxyType(merged_routing)
            param_specs = (
                build_param_specs(_original_endpoint(method))
                if merged_routing.get("typed")
                else None
            )

            for url in merged_routing["routes"]:
                endpoint = functools.partial(method)
                functools.update_wrapper(endpoint, method)
                endpoint.routing = frozen_routing
                _apply_param_specs(endpoint, param_specs)

                yield (url, endpoint)


def _check_and_complete_route_definition(
    controller_cls: type, submethod: Any, merged_routing: dict[str, Any]
) -> dict[str, Any]:
    fragment = dict(submethod.original_routing)

    routing_type = merged_routing.setdefault("type", fragment.get("type", "http"))
    if fragment.get("type") not in (None, routing_type):
        _logger.warning(
            "The endpoint %s changes the route type, using the original type: %r.",
            f"{controller_cls.__module__}.{controller_cls.__name__}.{submethod.__name__}",
            routing_type,
        )
    fragment["type"] = routing_type

    if bool(fragment.get("typed", merged_routing.get("typed", False))):
        fragment["typed"] = True

    default_auth = fragment.get("auth", merged_routing["auth"])
    default_mode = fragment.get("readonly", default_auth == "none")
    parent_readonly = merged_routing.setdefault("readonly", default_mode)
    child_readonly = fragment.get("readonly")
    if child_readonly not in (None, parent_readonly) and not callable(child_readonly):
        _logger.warning(
            "The endpoint %s made the route %s although its parent was defined as %s. Setting the route read/write.",
            f"{controller_cls.__module__}.{controller_cls.__name__}.{submethod.__name__}",
            "readonly" if child_readonly else "read/write",
            "readonly" if parent_readonly else "read/write",
        )
        fragment["readonly"] = False
    return fragment


def fragment_to_query_string(func: Callable) -> Callable:
    """Re-request the endpoint with the URL fragment turned into query args.

    OAuth2 and OAuth-like providers that use the implicit flow hand their
    answer back in the URL *fragment* (``#access_token=...``), which a browser
    never sends to the server -- so the endpoint sees no parameters at all.
    Wrapped, it answers that first, parameter-less request with a page whose
    only job is to move the fragment into the query string and navigate again;
    the second request carries the values and runs the real handler.

    ``debug`` is dropped because the web client appends it to the fragment on
    a debug session, and it alone would make the request look answered.

    Lives here rather than beside its first caller: it holds no state of any
    provider's, and being in ``odoo.http`` means an addon that needs it does
    not have to depend on an authentication provider to reach it.
    """

    @functools.wraps(func)
    def wrapper(self, *a, **kw):
        kw.pop("debug", False)
        if not kw:
            return Response("""<html><head><script>
                var l = window.location;
                var q = l.hash.substring(1);
                var r = l.pathname + l.search;
                if(q.length !== 0) {
                    var s = l.search ? (l.search === '?' ? '' : '&') : '?';
                    r = l.pathname + l.search + s + q;
                }
                if (r == l.pathname) {
                    r = '/';
                }
                window.location = r;
            </script></head><body></body></html>""")
        return func(self, *a, **kw)

    return wrapper

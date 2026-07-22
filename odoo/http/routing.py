import functools
import inspect
import logging
import warnings
from collections.abc import Callable, Generator, Iterable
from types import MappingProxyType
from typing import Any

from odoo.tools import unique
from odoo.tools.misc import submap

from ._params import build_param_specs, coerce_params
from .constants import ROUTING_KEYS
from .controller import Controller
from .dispatcher import _dispatchers
from .wrappers import Response

_logger = logging.getLogger(__name__)


def rule_routing_kwargs(endpoint: Callable) -> dict[str, Any]:
    """Build the werkzeug ``Rule`` keyword arguments for ``endpoint``.

    Returns the :data:`ROUTING_KEYS` subset of ``endpoint.routing``, appending
    ``OPTIONS`` to ``methods`` when an allow-list is set so a CORS preflight
    reaches the dispatcher instead of a ``405``. Shared by both routing maps
    (nodb and per-database) so they cannot drift on accepted methods.
    """
    routing = submap(endpoint.routing, ROUTING_KEYS)
    methods = routing.get("methods")
    if methods is not None and "OPTIONS" not in methods:
        routing["methods"] = [*methods, "OPTIONS"]
    return routing


def _route_param_filter(endpoint: Callable) -> tuple[bool, frozenset[str], str]:
    """Classify ``endpoint``'s parameters for request-arg filtering, ONCE.

    :returns: ``(accepts_var_keyword, accepted_named_params, bound_self_name)``
        — whether it has a ``**kwargs`` catch-all (accepts every arg), the names
        it accepts by keyword, and the name of its first parameter (the bound
        ``self``, supplied positionally by ``route_wrapper``).

    Classified once at decoration time instead of calling ``inspect.signature``
    (~7.5us) per request as :func:`~odoo.libs.func.filter_kwargs` did. Acceptance
    mirrors ``filter_kwargs`` (POSITIONAL_OR_KEYWORD / KEYWORD_ONLY by name,
    VAR_KEYWORD accepts all, POSITIONAL_ONLY / VAR_POSITIONAL not by keyword);
    ``test_session08`` locks the "called ignoring args {...}" contract.

    The first parameter (the controller instance) is EXCLUDED: it is bound
    positionally, so a same-named request arg (e.g. ``?self=1``) would otherwise
    raise ``got multiple values for argument 'self'`` — a 500 on every route.
    This exclusion is a deliberate divergence from ``filter_kwargs``.
    """
    accepts_var_keyword = False
    named: set[str] = set()
    params = list(inspect.signature(endpoint).parameters.values())
    bound_self_name = params[0].name if params else "self"
    for param in params[1:]:  # skip the bound controller ``self`` (params[0])
        if param.kind is inspect.Parameter.VAR_KEYWORD:
            accepts_var_keyword = True
        elif param.kind in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        ):
            named.add(param.name)
    return accepts_var_keyword, frozenset(named), bound_self_name


def route(route: str | Iterable[str] | None = None, **routing: Any) -> Callable:
    """
    Decorate a controller method to route incoming requests matching the
    given URL and options to the decorated method.

    .. warning::
        It is mandatory to re-decorate any method that is overridden in
        controller extensions but the arguments can be omitted. See
        :class:`~odoo.http.Controller` for more details.

    :param str | Iterable[str] route: The paths that the decorated
        method is serving. Incoming HTTP request paths matching this
        route will be routed to this decorated method. See `werkzeug
        routing documentation <https://werkzeug.palletsprojects.com/en/stable/routing/>`_
        for the format of route expressions.
    :param str type: The type of request: ``'http'`` (the default),
        ``'jsonrpc'`` (JSON-RPC 2.0 envelope) or ``'json2'`` (plain JSON
        body in, plain JSON out). It describes where to find the request
        parameters and how to serialize the response.
    :param str auth: The authentication method, one of the following:

        * ``'user'``: The user must be authenticated and the current
          request will be executed using the rights of the user.
        * ``'bearer'``: The user is authenticated using an "Authorization"
          request header, using the Bearer scheme with an API token.
          The request will be executed with the permissions of the
          corresponding user. If the header is missing, the request
          must belong to an authentication session, as for the "user"
          authentication method.
        * ``'public'``: The user may or may not be authenticated. If he
          isn't, the current request will be executed using the shared
          Public user.
        * ``'none'``: The method is always active, even if there is no
          database. Mainly used by the framework and authentication
          modules. The request code will not have any facilities to
          access the current user.
    :param Iterable[str] methods: A list of http methods (verbs) this
        route applies to. If not specified, all methods are allowed.
    :param str cors: The Access-Control-Allow-Origin cors directive value.
    :param bool csrf: Whether CSRF protection should be enabled for the
        route. Enabled by default for ``'http'``-type requests, disabled
        by default for ``'jsonrpc'``-type requests.
    :param bool typed: When ``True``, coerce and validate request parameters
        against the handler's type annotations (see :mod:`odoo.http._params`):
        an ``n: int`` parameter then arrives as a real ``int``, and a missing
        required parameter or a value that cannot be coerced yields a ``400``.
        A ``list[...]``-annotated parameter collects every repeated occurrence
        of its query/form key (``?a=1&a=2`` → ``[1, 2]``) on ``type='http'``
        routes. Only annotated parameters are affected; unannotated ones pass
        through unchanged. ``False`` by default.
    :param bool | Callable[[Controller, rule, dict], bool] readonly:
        Whether this endpoint should open a cursor on a read-only
        replica instead of (by default) the primary read/write database.
        When callable, it is invoked as ``readonly(controller, rule, args)``
        where ``controller`` is the controller instance, ``rule`` is the
        matched werkzeug routing rule, and ``args`` is the dict of URL
        path parameters. It must return a boolean.

        If a ``readonly=True`` endpoint nevertheless issues a write, the request
        is transparently re-dispatched on a read/write cursor — which means
        **the handler body runs a second time**. Keep non-transactional side
        effects (sending email, outbound HTTP calls, consuming a one-time token)
        out of the handler until after the first database write, or they execute
        twice. A WARNING naming the route is logged on every such promotion.
    :param Callable[[Exception], Response] handle_params_access_error:
        Implement a custom behavior if an error occurred when retrieving
        the record from the URL parameters (access error or missing error).
    :param str captcha: The action name of the captcha. When set the
        request will be validated against a captcha implementation. Upon
        failing these requests will return a UserError.
    :param bool save_session: Whether it should set a session_id cookie
        on the http response and save dirty session on disk. ``False``
        by default for ``auth='bearer'``. ``True`` by default otherwise.
    :param int | Callable[[Controller], int] max_content_length:
        Per-route override for the request body size limit (in bytes).
        When callable, it is invoked as ``max_content_length(controller)``
        and must return the limit as an int. If omitted, the default
        :data:`DEFAULT_MAX_CONTENT_LENGTH` applies.
    """

    def decorator(endpoint: Callable) -> Callable:
        fname = f"<function {endpoint.__module__}.{endpoint.__name__}>"

        # Sanitize the routing
        if routing.get("type") == "json":
            warnings.warn(
                "Since 19.0, @route(type='json') is a deprecated alias to @route(type='jsonrpc')",
                DeprecationWarning,
                stacklevel=2,
            )
            routing["type"] = "jsonrpc"
        route_type = routing.get("type", "http")
        if route_type not in _dispatchers:
            # Use a real exception rather than ``assert`` so ``python -O`` does
            # not let unknown types through to a later KeyError at dispatch.
            raise ValueError(
                f"@route(type={route_type!r}) is not one of {list(_dispatchers)}"
            )
        if route:
            routing["routes"] = [route] if isinstance(route, str) else route
        wrong = routing.pop("method", None)
        if wrong is not None:
            _logger.warning(
                "%s defined with invalid routing parameter 'method', assuming 'methods'",
                fname,
            )
            routing["methods"] = wrong
        # NB: ``save_session``'s bearer default is NOT baked in here. Doing so put
        # a concrete ``False`` in this fragment's routing, which then leaked
        # through the inheritance merge: an extension re-decorating a bearer route
        # as ``auth='user'`` (without restating ``save_session``) silently kept the
        # stateless ``False`` and never persisted its session cookie. The default
        # is instead resolved from the *final merged* auth in
        # :func:`_generate_routing_rules`, so it tracks the auth the route actually
        # ends up with. An explicit ``save_session=`` on any fragment still wins.

        # Classify the endpoint's accepted params once; route_wrapper runs on
        # every request and ``inspect.signature`` is comparatively expensive.
        accepts_var_keyword, accepted_params, bound_self_name = _route_param_filter(
            endpoint
        )

        # Opt-in typed routing: coerce/validate annotated params against the
        # handler's type hints (see odoo.http._params). ``None`` for the common
        # untyped route, so route_wrapper pays nothing.
        param_specs = build_param_specs(endpoint) if routing.get("typed") else None

        # ``controller_self`` is positional-only (``/``) and not named ``self``:
        # the wrapper is called as ``endpoint(**request.params)``, so a request
        # arg named ``self`` lands in ``**params`` (to be filtered) instead of
        # colliding with the bound instance.
        @functools.wraps(endpoint)
        def route_wrapper(controller_self, /, *args, **params):
            if accepts_var_keyword:
                params_ok = params
                params_ko = None
                # ``**kwargs`` forwards every arg, but the first positional is
                # still the bound ``self``; drop a same-named request arg.
                if bound_self_name in params:
                    params_ok = {
                        k: v for k, v in params.items() if k != bound_self_name
                    }
                    params_ko = {bound_self_name}
            elif params.keys() <= accepted_params:
                # Hot path: every arg is accepted, so forward ``params`` unchanged
                # instead of rebuilding the dict and an empty set difference.
                params_ok = params
                params_ko = None
            else:
                params_ok = {k: v for k, v in params.items() if k in accepted_params}
                params_ko = params.keys() - accepted_params
            if params_ko:
                # ``params_ko`` is already a set in every branch reaching here.
                _logger.warning("%s called ignoring args %s", fname, params_ko)

            if param_specs is not None:
                # Typed route: coerce/validate annotated params (raises 400 on a
                # missing-required or uncoercible value).
                params_ok = coerce_params(params_ok, param_specs)

            result = endpoint(controller_self, *args, **params_ok)
            if (
                routing["type"] == "http"
            ):  # _generate_routing_rules() ensures type is set
                # Pass ``fname`` so ``Response.load``'s misuse diagnostics name
                # the offending endpoint instead of the literal "<function>".
                return Response.load(result, fname)
            return result

        route_wrapper.original_routing = routing
        route_wrapper.original_endpoint = endpoint
        if param_specs:
            # Names of ``list``-annotated params, so ``HttpDispatcher.dispatch``
            # can re-read repeated query/form keys via ``getlist`` — the flat
            # ``get_http_params`` merge keeps only one value per key. Set only
            # when non-empty so untyped routes carry no extra attribute.
            typed_list_params = frozenset(
                name for name, spec in param_specs.items() if spec.target is list
            )
            if typed_list_params:
                route_wrapper.typed_list_params = typed_list_params
        return route_wrapper

    return decorator


def _generate_routing_rules(
    modules: list[str], nodb_only: bool, converters: dict | None = None
) -> Generator[tuple[str, Any]]:
    """
    Two-fold algorithm used to (1) determine which method in the
    controller inheritance tree should bind to what URL with respect to
    the list of installed modules and (2) merge the various @route
    arguments of said method with the @route arguments of the method it
    overrides.
    """

    def is_valid(cls: type) -> bool:
        """Determine if the class is defined in an addon."""
        path = cls.__module__.split(".")
        return path[:2] == ["odoo", "addons"] and path[2] in modules

    def get_leaf_classes(cls: type) -> list[type]:
        """
        Find the classes that have no child and that have ``cls`` as
        ancestor.
        """
        result = []
        for subcls in cls.__subclasses__():
            if is_valid(subcls):
                result.extend(get_leaf_classes(subcls))
        if not result and is_valid(cls):
            result.append(cls)
        return result

    def build_controllers() -> Generator[Controller]:
        """
        Create dummy controllers that inherit only from the controllers
        defined at the given ``modules`` (often system wide modules or
        installed modules). Modules in this context are Odoo addons.
        """
        # Controllers defined outside of odoo addons are outside of the
        # controller inheritance/extension mechanism.
        yield from (ctrl() for ctrl in Controller.children_classes.get("", []))

        # Controllers defined inside of odoo addons can be extended in
        # other installed addons. Rebuild the class inheritance here.
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
            # Skip this method if it is not @route decorated anywhere in
            # the hierarchy
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
                # 'type': 'http',  # set below
                "auth": "user",
                "methods": None,
                "routes": [],
            }

            # Walk the MRO ancestors-first, skipping Controller and object. Filter
            # by identity, not a ``mro()[:-2]`` slice, which would drop mixins
            # after Controller and lose their ``@route`` decorators.
            ancestors = [
                cls
                for cls in reversed(type(ctrl).mro())
                if cls is not Controller and cls is not object
            ]
            defining_cls = None
            for cls in unique(ancestors):  # ancestors first
                if method_name not in cls.__dict__:
                    continue
                submethod = getattr(cls, method_name)

                if not hasattr(submethod, "original_routing"):
                    # An override that forgot to re-apply @route: log once and
                    # skip (auto-decorating would mask the missing decorator).
                    _logger.warning(
                        "The endpoint %s is overridden without @route(); skipping this override.",
                        f"{cls.__module__}.{cls.__name__}.{method_name}",
                    )
                    continue

                # Remember the most-derived ancestor that declared a @route
                # fragment, so the "without any route" warning names a real class.
                # The loop variable ``cls`` would instead leak the synthetic
                # merged controller (``type(name, ...)`` above).
                defining_cls = cls

                _check_and_complete_route_definition(cls, submethod, merged_routing)

                merged_routing.update(submethod.original_routing)

            if not merged_routing["routes"]:
                owner = defining_cls if defining_cls is not None else type(ctrl)
                _logger.warning(
                    "%s is a controller endpoint without any route, skipping.",
                    f"{owner.__module__}.{owner.__name__}.{method_name}",
                )
                continue

            if nodb_only and merged_routing["auth"] != "none":
                continue

            # Resolve ``save_session``'s default from the FINAL merged auth (see
            # the ``route`` decorator): a ``bearer`` route is stateless by default,
            # everything else persists its session. An explicit ``save_session=``
            # anywhere in the chain is already in ``merged_routing`` and wins.
            merged_routing.setdefault(
                "save_session", merged_routing["auth"] != "bearer"
            )

            # Freeze the merged routing so dispatchers can't mutate it at request
            # time; convert the ``methods`` list to a tuple too.
            if isinstance(merged_routing.get("methods"), list):
                merged_routing["methods"] = tuple(merged_routing["methods"])
            frozen_routing = MappingProxyType(merged_routing)

            for url in merged_routing["routes"]:
                # Duplicate the function (partial + update_wrapper) and set the
                # merged routing ONLY on the copy, so the original method stays
                # immutable while keeping ``original_routing``/``original_endpoint``.
                endpoint = functools.partial(method)
                functools.update_wrapper(endpoint, method)
                endpoint.routing = frozen_routing

                yield (url, endpoint)


def _check_and_complete_route_definition(
    controller_cls: type, submethod: Any, merged_routing: dict[str, Any]
) -> None:
    """Verify and complete the route definition.

    **Mutates** ``submethod.original_routing`` in place to fill inferred
    ``type`` / ``readonly`` keys (hence ``_complete_``) so later ancestor passes
    see the completed dict. Also warns when an override changes the routing type
    or read/write mode.

    :param submethod: route method
    :param dict merged_routing: accumulated routing values
    """
    default_type = submethod.original_routing.get("type", "http")
    routing_type = merged_routing.setdefault("type", default_type)
    if submethod.original_routing.get("type") not in (None, routing_type):
        _logger.warning(
            "The endpoint %s changes the route type, using the original type: %r.",
            f"{controller_cls.__module__}.{controller_cls.__name__}.{submethod.__name__}",
            routing_type,
        )
    submethod.original_routing["type"] = routing_type

    # Param coercion (``typed=True``) is compiled into each wrapper AT DECORATION
    # TIME from its own ``@route`` arguments — it cannot be inherited through the
    # routing merge. An override that forgets to restate ``typed=True`` therefore
    # silently loses coercion while the merged routing (and the OpenAPI document)
    # still advertise it; warn so the divergence is visible.
    if merged_routing.get("typed") and "typed" not in submethod.original_routing:
        _logger.warning(
            "The endpoint %s overrides a typed=True route without restating "
            "typed=True; parameter coercion is DISABLED for this override.",
            f"{controller_cls.__module__}.{controller_cls.__name__}.{submethod.__name__}",
        )

    default_auth = submethod.original_routing.get("auth", merged_routing["auth"])
    default_mode = submethod.original_routing.get("readonly", default_auth == "none")
    parent_readonly = merged_routing.setdefault("readonly", default_mode)
    child_readonly = submethod.original_routing.get("readonly")
    if child_readonly not in (None, parent_readonly) and not callable(child_readonly):
        _logger.warning(
            "The endpoint %s made the route %s although its parent was defined as %s. Setting the route read/write.",
            f"{controller_cls.__module__}.{controller_cls.__name__}.{submethod.__name__}",
            "readonly" if child_readonly else "read/write",
            "readonly" if parent_readonly else "read/write",
        )
        submethod.original_routing["readonly"] = False

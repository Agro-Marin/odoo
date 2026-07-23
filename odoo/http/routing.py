from __future__ import annotations

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

from ._params import build_param_specs, coerce_params
from .constants import ROUTING_KEYS
from .controller import Controller
from .dispatcher import _dispatchers
from .wrappers import Response

_logger = logging.getLogger(__name__)

# Every ``@route`` keyword the framework itself consumes, plus the werkzeug
# ``Rule`` kwargs forwarded via :data:`ROUTING_KEYS`. ``endpoint.routing`` is an
# open extension namespace — modules read their own keys from it (website's
# ``sitemap=``, auth_timeout's ``check_identity=``, ...) — so unknown keys can't
# be *rejected*; but an undeclared key at decoration time has historically been
# a typo (``raedonly=True``) silently stored and ignored. Extension modules
# declare their keys with :func:`register_routing_parameters` at import time
# (dependencies import before their dependents' controllers are decorated, so
# declarations always precede use); anything undeclared draws a warning.
_KNOWN_ROUTING_PARAMETERS: set[str] = {
    # consumed by the decorator / dispatchers / ir.http
    "auth",
    "captcha",
    "cors",
    "csrf",
    "handle_params_access_error",
    "max_content_length",
    "readonly",
    "save_session",
    "type",
    "typed",
    *ROUTING_KEYS,
    # Platform vocabulary declared HERE, not by its consumers: these keys are
    # set *speculatively* by base-layer controllers (``web.web_login`` carries
    # ``website=``/``multilang=``/``sitemap=``/``list_as_website_content=``)
    # so that the consumer honours them WHEN installed — and that consumer
    # (website / http_routing) imports long after the base layer decorated its
    # routes, so consumer-side register_routing_parameters() would warn
    # spuriously at every startup.
    "website",  # consumed by http_routing/website ir_http
    "multilang",  # consumed by http_routing ir_http (lang-prefixed routing)
    "sitemap",  # consumed by website sitemap generation
    "list_as_website_content",  # consumed by website_technical_page
}


def register_routing_parameters(*names: str) -> None:
    """Declare extension ``@route`` parameter names as known.

    Call at module import time, before any controller using the parameter is
    decorated — conventionally from the owning addon's ``__init__.py``. Only
    suppresses the unknown-parameter warning; storage in ``endpoint.routing``
    is unconditional either way.
    """
    _KNOWN_ROUTING_PARAMETERS.update(names)


class LazyCompiledBuilder:
    """Defer a werkzeug ``Rule``'s URL-builder compilation until first ``url_for``.

    ``Rule.compile`` builds both a matcher and a builder; the builder
    (:meth:`werkzeug.routing.Rule._compile_builder`) dominates routing-map
    construction, yet most rules are only ever *matched* (inbound dispatch),
    never *built* (``url_for``). This descriptor stands in for the compiled
    builder and materialises it on the first call, so map construction pays only
    for the matcher.
    """

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
        # Rule.compile binds the result via _compile_builder(...).__get__(self, None),
        # so the builder must be a descriptor; returning self here keeps this lazy
        # wrapper alive through that binding.
        return self

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        # Routing maps are shared across worker threads, so the first url_for
        # of a rule can race. Compilation is idempotent: concurrent first calls
        # may each compile (last write wins), which is safe; what must NOT
        # happen is deleting the source attributes after publishing — a peer
        # that passed the ``None`` check would then crash on ``self.rule``
        # (AttributeError → 500). Keep the attributes; they are three
        # references on an object the Map retains anyway.
        fn = self._callable
        if fn is None:
            fn = self._compile_builder(self._append_unknown).__get__(self.rule, None)
            self._callable = fn
        return fn(*args, **kwargs)


class FasterRule(werkzeug.routing.Rule):
    """Make ``_compile_builder`` lazy: it dominates routing-map generation but rules are rarely built."""

    def _compile_builder(self, append_unknown: bool = True) -> LazyCompiledBuilder:
        return LazyCompiledBuilder(self, super()._compile_builder, append_unknown)


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
            # Materialize to a list: the routing maps (nodb + one per database)
            # each iterate ``routes``, so a one-shot iterable (generator) would
            # register the routes on the first build and vanish from the rest.
            routing["routes"] = [route] if isinstance(route, str) else list(route)
        wrong = routing.pop("method", None)
        if wrong is not None:
            _logger.warning(
                "%s defined with invalid routing parameter 'method', assuming 'methods'",
                fname,
            )
            routing["methods"] = wrong
        # ``routes`` is decorator-internal (set above from the positional
        # argument); everything else must be declared (see
        # ``_KNOWN_ROUTING_PARAMETERS``) or it is very likely a typo that
        # silently disables the option it meant to set.
        unknown = routing.keys() - _KNOWN_ROUTING_PARAMETERS - {"routes"}
        if unknown:
            _logger.warning(
                "%s defined with unknown @route parameter(s) %s; they are kept "
                "in endpoint.routing, but no module declared them via "
                "odoo.http.register_routing_parameters() — possible typo.",
                fname,
                sorted(unknown),
            )
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
            # The route's type decides whether the result is coerced into a
            # Response. A fragment may omit ``type`` (inheriting it), so read
            # the merged type stamped on this wrapper by
            # ``_check_and_complete_route_definition`` during the map build;
            # before any build (a direct call in tests) fall back to the
            # fragment's own declaration.
            route_type = getattr(route_wrapper, "_merged_route_type", None) or (
                routing.get("type", "http")
            )
            if route_type == "http":
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
) -> dict[str, Any]:
    """Return ``submethod``'s effective routing contribution for the merge.

    Starts from a copy of ``submethod.original_routing`` and corrects on the
    copy the keys an override may not change (a conflicting ``type`` keeps the
    original; a boolean ``readonly`` flip forces read/write), warning on each
    conflict. ``merged_routing`` carries the walk state (``type`` / ``readonly``
    are filled via ``setdefault``); the caller applies the returned fragment
    with ``merged_routing.update(...)``.

    The declared ``original_routing`` is NEVER mutated. The pre-split code
    wrote the corrections back into it, which leaked one build's merge context
    into every later build — routing maps are rebuilt per database with
    different installed-module sets, so a later build merged against
    contaminated declarations — and made the conflict warnings one-shot per
    process. Corrections now replay from pristine declarations on every build
    (order-independent), and a genuine misconfiguration warns on each map build.

    Patch point: the ``odoo.http`` re-export of this name is for importing
    only — ``_generate_routing_rules`` resolves it from THIS module's
    namespace, so wrappers must patch
    ``odoo.http.routing._check_and_complete_route_definition`` and return the
    inner call's fragment (see ``test_lint.tests.test_routes``).

    :param submethod: route method
    :param dict merged_routing: accumulated routing values
    :returns: the corrected copy of ``submethod.original_routing``
    """
    fragment = dict(submethod.original_routing)

    routing_type = merged_routing.setdefault("type", fragment.get("type", "http"))
    if fragment.get("type") not in (None, routing_type):
        _logger.warning(
            "The endpoint %s changes the route type, using the original type: %r.",
            f"{controller_cls.__module__}.{controller_cls.__name__}.{submethod.__name__}",
            routing_type,
        )
    fragment["type"] = routing_type
    # Stamp the resolved type on the wrapper FUNCTION (not the declaration
    # dict): ``route_wrapper`` needs it at dispatch time to decide Response
    # coercion, including for mid-chain wrappers reached via ``super()`` calls.
    # The value depends only on the fixed class hierarchy (first-declared type
    # wins), so re-stamping on every build writes the same value — no
    # cross-build contamination, unlike the ``readonly`` correction below.
    submethod._merged_route_type = routing_type

    # Param coercion (``typed=True``) is compiled into each wrapper AT DECORATION
    # TIME from its own ``@route`` arguments — it cannot be inherited through the
    # routing merge. An override that forgets to restate ``typed=True`` therefore
    # silently loses coercion while the merged routing (and the OpenAPI document)
    # still advertise it; warn so the divergence is visible.
    if merged_routing.get("typed") and "typed" not in fragment:
        _logger.warning(
            "The endpoint %s overrides a typed=True route without restating "
            "typed=True; parameter coercion is DISABLED for this override.",
            f"{controller_cls.__module__}.{controller_cls.__name__}.{submethod.__name__}",
        )

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

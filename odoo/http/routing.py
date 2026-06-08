import functools
import inspect
import logging
import warnings
from collections.abc import Callable, Generator, Iterable
from types import MappingProxyType
from typing import Any

from odoo.libs.func import filter_kwargs
from odoo.tools import unique

from .controller import Controller
from .dispatcher import _dispatchers
from .wrappers import Response

_logger = logging.getLogger(__name__)


def route(route: str | Iterable[str] | None = None, **routing: Any) -> Callable:
    """
    Decorate a controller method in order to route incoming requests
    matching the given URL and options to the decorated method.

    .. warning::
        It is mandatory to re-decorate any method that is overridden in
        controller extensions but the arguments can be omitted. See
        :class:`~odoo.http.Controller` for more details.

    :param str | Iterable[str] route: The paths that the decorated
        method is serving. Incoming HTTP request paths matching this
        route will be routed to this decorated method. See `werkzeug
        routing documentation <https://werkzeug.palletsprojects.com/en/stable/routing/>`_
        for the format of route expressions.
    :param str type: The type of request, either ``'jsonrpc'`` or
        ``'http'``. It describes where to find the request parameters
        and how to serialize the response.
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
    :param bool | Callable[[Controller, rule, dict], bool] readonly:
        Whether this endpoint should open a cursor on a read-only
        replica instead of (by default) the primary read/write database.
        When callable, it is invoked as ``readonly(controller, rule, args)``
        where ``controller`` is the controller instance, ``rule`` is the
        matched werkzeug routing rule, and ``args`` is the dict of URL
        path parameters. It must return a boolean.
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
        if routing.get("auth") == "bearer":
            routing.setdefault("save_session", False)  # stateless

        @functools.wraps(endpoint)
        def route_wrapper(self, *args, **params):
            params_ok = filter_kwargs(endpoint, params)
            params_ko = set(params) - set(params_ok)
            if params_ko:
                _logger.warning("%s called ignoring args %s", fname, params_ko)

            result = endpoint(self, *args, **params_ok)
            if (
                routing["type"] == "http"
            ):  # _generate_routing_rules() ensures type is set
                return Response.load(result)
            return result

        route_wrapper.original_routing = routing
        route_wrapper.original_endpoint = endpoint
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

            # Walk the MRO ancestors-first, but skip Controller itself and
            # object. Using a slice like ``mro()[:-2]`` silently drops mixins
            # that appear after Controller in the base list; filter by identity
            # instead so those mixins' ``@route`` decorators merge correctly.
            ancestors = [
                cls
                for cls in reversed(type(ctrl).mro())
                if cls is not Controller and cls is not object
            ]
            for cls in unique(ancestors):  # ancestors first
                if method_name not in cls.__dict__:
                    continue
                submethod = getattr(cls, method_name)

                if not hasattr(submethod, "original_routing"):
                    # An override that forgot to re-apply @route. Log once and
                    # skip: auto-decorating with route() produced an empty
                    # routing dict that contributed nothing to the merged
                    # routing while silently masking the missing decorator.
                    _logger.warning(
                        "The endpoint %s is overridden without @route(); skipping this override.",
                        f"{cls.__module__}.{cls.__name__}.{method_name}",
                    )
                    continue

                _check_and_complete_route_definition(cls, submethod, merged_routing)

                merged_routing.update(submethod.original_routing)

            if not merged_routing["routes"]:
                _logger.warning(
                    "%s is a controller endpoint without any route, skipping.",
                    f"{cls.__module__}.{cls.__name__}.{method_name}",
                )
                continue

            if nodb_only and merged_routing["auth"] != "none":
                continue

            # Freeze the merged routing so dispatchers cannot accidentally
            # mutate it at request time. The ``methods`` value (a list)
            # remains mutable; convert to a tuple to lock the externally
            # observable contract.
            if isinstance(merged_routing.get("methods"), list):
                merged_routing["methods"] = tuple(merged_routing["methods"])
            frozen_routing = MappingProxyType(merged_routing)

            for url in merged_routing["routes"]:
                # duplicates the function (partial) with a copy of the
                # original __dict__ (update_wrapper) to keep a reference
                # to `original_routing` and `original_endpoint`, assign
                # the merged routing ONLY on the duplicated function to
                # ensure method's immutability.
                endpoint = functools.partial(method)
                functools.update_wrapper(endpoint, method)
                endpoint.routing = frozen_routing

                yield (url, endpoint)


def _check_and_complete_route_definition(
    controller_cls: type, submethod: Any, merged_routing: dict[str, Any]
) -> None:
    """Verify and complete the route definition.

    **Mutates** ``submethod.original_routing`` in place to fill in inferred
    ``type`` / ``readonly`` keys so subsequent ancestor passes see the same
    completed routing dict — the function is named ``_complete_`` to flag
    that side effect, even though it reads as a validation step.

    * Ensure 'type' is defined on each method's own routing.
    * Ensure overrides don't change the routing type or the read/write mode

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

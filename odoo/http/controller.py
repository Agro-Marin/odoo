import collections
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import odoo.api


class Controller:
    """
    Class mixin that provides module controllers the ability to serve
    content over http and to be extended in child modules.

    Each class :ref:`inheriting <python:tut-inheritance>` from
    :class:`~odoo.http.Controller` can use the :func:`~odoo.http.route`
    decorator to route matching incoming web requests to decorated
    methods.

    Like models, controllers can be extended by other modules. The
    extension mechanism is different because controllers can work in a
    database-free environment and therefore cannot use
    :class:`~odoo.api.Registry`.

    To *override* a controller, :ref:`inherit <python:tut-inheritance>`
    from its class, override relevant methods and re-expose them with
    :func:`~odoo.http.route`. Please note that the decorators of all
    methods are combined, if the overriding method's decorator has no
    argument all previous ones will be kept, any provided argument will
    override previously defined ones.

    .. code-block:: python

        class GreetingController(odoo.http.Controller):
            @route("/greet", type="http", auth="public")
            def greeting(self):
                return "Hello"


        class UserGreetingController(GreetingController):
            @route(auth="user")  # override auth, keep path and type
            def greeting(self):
                return super().greeting()
    """

    children_classes: collections.defaultdict[str, list[type[Controller]]] = (
        collections.defaultdict(list)
    )  # indexed by module

    @classmethod
    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if Controller in cls.__bases__:
            path = cls.__module__.split(".")
            module = path[2] if path[:2] == ["odoo", "addons"] else ""
            Controller.children_classes[module].append(cls)

    @property
    def env(self) -> odoo.api.Environment | None:
        from . import request  # lazy import

        return request.env if request else None

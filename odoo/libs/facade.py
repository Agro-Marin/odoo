"""Facade pattern implementation utilities.

Provides proxy classes for wrapping and exposing subsets of object interfaces.
"""

__all__ = ["Proxy", "ProxyAttr", "ProxyFunc", "ProxyMeta"]

import functools
import inspect
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable


class ProxyAttr[T = Any]:
    """Expose an attribute of the wrapped instance on a `Proxy`, with optional type casting.

    :meth:`__set_name__` swaps this descriptor out for a plain ``property``, so
    the ``__get__``/``__set__`` below never run — they exist only so a type
    checker, which cannot follow that swap, sees the proxied attribute as its
    cast type instead of as a ``ProxyAttr`` instance.
    """

    _cast__: Callable[..., Any] | bool

    def __init__(self, cast: Callable[..., T] | bool = False) -> None:
        """Store the optional ``cast`` applied to the attribute on read."""
        self._cast__ = cast

    if TYPE_CHECKING:

        def __get__(self, instance: Any, owner: type | None = None) -> T:
            """Type-checker view of reading the proxied attribute."""

        def __set__(self, instance: Any, value: T) -> None:
            """Type-checker view of writing the proxied attribute."""

    def __set_name__(self, owner: type, name: str) -> None:
        """Install a property on ``owner`` proxying ``name`` to the wrapped instance."""
        cast = self._cast__
        if cast:

            def getter(self: Any) -> Any:
                value = getattr(self._wrapped__, name)
                return cast(value) if value is not None else None

        else:

            def getter(self: Any) -> Any:
                return getattr(self._wrapped__, name)

        def setter(self: Any, value: Any) -> None:
            return setattr(self._wrapped__, name, value)

        setattr(owner, name, property(getter, setter))


class ProxyFunc[T = Any]:
    """Expose a method of the wrapped instance on a `Proxy`, with optional casting of the return value.

    Like :class:`ProxyAttr`, the ``__call__`` below is type-checker-only:
    :meth:`__set_name__` replaces this descriptor with the wrapping function.
    """

    _cast__: Callable[..., Any] | bool | None

    def __init__(self, cast: Callable[..., T] | bool | None = False) -> None:
        """Store the optional ``cast`` applied to the function's return value."""
        self._cast__ = cast

    if TYPE_CHECKING:

        def __call__(self, *args: Any, **kwargs: Any) -> T:
            """Type-checker view of calling the proxied method."""

    def __set_name__(self, owner: type, name: str) -> None:
        """Install a wrapper on ``owner`` forwarding ``name`` to the wrapped instance.

        The three wrappers are named rather than three conditional definitions
        of one ``wrap_func``: same-name variants with different signatures are
        a redefinition a type checker cannot reconcile, and nine near-identical
        bodies hid how little actually differs between them.
        """
        func = getattr(owner._wrapped__, name)
        descriptor = inspect.getattr_static(owner._wrapped__, name)
        cast = self._cast__

        if cast is None:

            def finish(result: Any) -> Any:
                """Discard the result: this member is declared as returning None."""
                return None

        elif cast:

            def finish(result: Any) -> Any:
                """Apply the declared cast, preserving ``None``."""
                return cast(result) if result is not None else None

        else:

            def finish(result: Any) -> Any:
                """Pass the result through uncast."""
                return result

        def static_wrapper(*args: Any, **kwargs: Any) -> Any:
            """Forward to the wrapped staticmethod."""
            return finish(func(*args, **kwargs))

        def class_wrapper(cls: type, *args: Any, **kwargs: Any) -> Any:
            """Forward to the wrapped classmethod, dropping the proxy class."""
            return finish(func(*args, **kwargs))

        def instance_wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            """Forward to the wrapped instance's bound method."""
            return finish(func(self._wrapped__, *args, **kwargs))

        wrapper: Any
        if isinstance(descriptor, staticmethod):
            wrapper = static_wrapper
        elif isinstance(descriptor, classmethod):
            wrapper = class_wrapper
        else:
            wrapper = instance_wrapper
        functools.update_wrapper(wrapper, func)

        if isinstance(descriptor, staticmethod):
            wrapper = staticmethod(wrapper)
        elif isinstance(descriptor, classmethod):
            wrapper = classmethod(wrapper)

        setattr(owner, name, wrapper)


class ProxyMeta(type):
    """Metaclass for :class:`Proxy` subclasses.

    Auto-installs ``__repr__``/``__str__`` proxies and links the proxy class to
    its wrapped class so docstring and signature introspection see through it.
    """

    def __new__(
        cls,
        clsname: str,
        bases: tuple[type, ...],
        attrs: dict[str, Any],
    ) -> ProxyMeta:
        """Build the proxy class, defaulting ``__repr__``/``__str__`` to proxies."""
        attrs.update(
            {func: ProxyFunc() for func in ("__repr__", "__str__") if func not in attrs}
        )
        proxy_class = super().__new__(cls, clsname, bases, attrs)
        functools.update_wrapper(
            proxy_class, proxy_class._wrapped__, assigned=("__doc__",), updated=[]
        )
        return proxy_class


class Proxy(metaclass=ProxyMeta):
    """A proxy class implementing the Facade pattern.

    This class delegates to an underlying instance while exposing a curated subset of its attributes and methods.
    Useful for controlling access, simplifying interfaces, or adding cross-cutting concerns.
    """

    _wrapped__: type = object

    def __init__(self, instance: Any) -> None:
        """Initialize the proxy by setting the wrapped instance.

        :param instance: The instance of the class to be wrapped.
        """
        object.__setattr__(self, "_wrapped__", instance)

    @property
    def __class__(self) -> type:
        """Report the wrapped class so ``isinstance`` checks see through the proxy."""
        return type(self)._wrapped__

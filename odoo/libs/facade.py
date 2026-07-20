"""Facade pattern implementation utilities.

Provides proxy classes for wrapping and exposing subsets of object interfaces.
"""

__all__ = ["Proxy", "ProxyAttr", "ProxyFunc", "ProxyMeta"]

import functools
import inspect
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable


class ProxyAttr:
    """Expose an attribute of the wrapped instance on a `Proxy`, with optional type casting."""

    def __init__(self, cast: Callable[..., Any] | bool = False) -> None:
        """Store the optional ``cast`` applied to the attribute on read."""
        self._cast__ = cast

    def __set_name__(self, owner: type, name: str) -> None:
        """Install a property on ``owner`` proxying ``name`` to the wrapped instance."""
        cast = self._cast__
        if cast:

            def getter(self: Any) -> Any:
                value = getattr(self._wrapped__, name)
                return cast(value) if value is not None else None  # type: ignore[operator]

        else:

            def getter(self: Any) -> Any:
                return getattr(self._wrapped__, name)

        def setter(self: Any, value: Any) -> None:
            return setattr(self._wrapped__, name, value)

        setattr(owner, name, property(getter, setter))


class ProxyFunc:
    """Expose a method of the wrapped instance on a `Proxy`, with optional casting of the return value."""

    def __init__(self, cast: Callable[..., Any] | bool = False) -> None:
        """Store the optional ``cast`` applied to the function's return value."""
        self._cast__ = cast

    def __set_name__(self, owner: type, name: str) -> None:
        """Install a wrapper on ``owner`` forwarding ``name`` to the wrapped instance."""
        func = getattr(owner._wrapped__, name)
        descriptor = inspect.getattr_static(owner._wrapped__, name)
        cast = self._cast__

        if isinstance(descriptor, staticmethod):
            if cast:

                def wrap_func(*args: Any, **kwargs: Any) -> Any:
                    result = func(*args, **kwargs)
                    return cast(result) if result is not None else None  # type: ignore[operator]

            elif cast is None:

                def wrap_func(*args: Any, **kwargs: Any) -> None:
                    func(*args, **kwargs)

            else:

                def wrap_func(*args: Any, **kwargs: Any) -> Any:
                    return func(*args, **kwargs)

            functools.update_wrapper(wrap_func, func)
            wrap_func = staticmethod(wrap_func)

        elif isinstance(descriptor, classmethod):
            if cast:

                def wrap_func(cls: type, *args: Any, **kwargs: Any) -> Any:
                    result = func(*args, **kwargs)
                    return cast(result) if result is not None else None  # type: ignore[operator]

            elif cast is None:

                def wrap_func(cls: type, *args: Any, **kwargs: Any) -> None:
                    func(*args, **kwargs)

            else:

                def wrap_func(cls: type, *args: Any, **kwargs: Any) -> Any:
                    return func(*args, **kwargs)

            functools.update_wrapper(wrap_func, func)
            wrap_func = classmethod(wrap_func)

        else:
            if cast:

                def wrap_func(self: Any, *args: Any, **kwargs: Any) -> Any:
                    result = func(self._wrapped__, *args, **kwargs)
                    return cast(result) if result is not None else None  # type: ignore[operator]

            elif cast is None:

                def wrap_func(self: Any, *args: Any, **kwargs: Any) -> None:
                    func(self._wrapped__, *args, **kwargs)

            else:

                def wrap_func(self: Any, *args: Any, **kwargs: Any) -> Any:
                    return func(self._wrapped__, *args, **kwargs)

            functools.update_wrapper(wrap_func, func)

        setattr(owner, name, wrap_func)


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
        # Copy ONLY the wrapped class's docstring (and, via update_wrapper's
        # unconditional ``__wrapped__`` assignment, keep ``inspect.signature``
        # following through to it). The default ``assigned`` would also copy
        # ``__name__``/``__qualname__``/``__module__``, shadowing the proxy's own
        # identity — that made e.g. ``type(http.Response).__name__`` report
        # ``'_Response'`` and mislabel the class in reprs and tracebacks.
        # ``updated=[]`` prevents merging the wrapped ``__dict__``.
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

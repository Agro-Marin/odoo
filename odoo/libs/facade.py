__all__ = ["Proxy", "ProxyAttr", "ProxyFunc", "ProxyMeta"]

import functools
import inspect
from typing import TYPE_CHECKING, Any, Literal, cast

if TYPE_CHECKING:
    from collections.abc import Callable


class ProxyAttr[T = Any]:
    _cast__: Callable[..., Any] | Literal[False]

    def __init__(self, cast: Callable[..., T] | Literal[False] = False) -> None:
        self._cast__ = cast

    if TYPE_CHECKING:

        def __get__(self, instance: Any, owner: type | None = None) -> T:
            pass

        def __set__(self, instance: Any, value: T) -> None:
            pass

    def __set_name__(self, owner: type[Proxy], name: str) -> None:
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
    _cast__: Callable[..., Any] | Literal[False] | None

    def __init__(self, cast: Callable[..., T] | Literal[False] | None = False) -> None:
        self._cast__ = cast

    if TYPE_CHECKING:

        def __call__(self, *args: Any, **kwargs: Any) -> T:
            pass

    def __set_name__(self, owner: type[Proxy], name: str) -> None:
        func = getattr(owner._wrapped__, name)
        descriptor = inspect.getattr_static(owner._wrapped__, name)
        cast = self._cast__

        if cast is None:

            def finish(result: Any) -> Any:  # noqa: ARG001  the three conditional variants must share one signature
                return None

        elif cast:

            def finish(result: Any) -> Any:
                return cast(result) if result is not None else None

        else:

            def finish(result: Any) -> Any:
                return result

        def static_wrapper(*args: Any, **kwargs: Any) -> Any:
            return finish(func(*args, **kwargs))

        def class_wrapper(cls: type, *args: Any, **kwargs: Any) -> Any:  # noqa: ARG001  classmethod signature; the wrapped func does not take cls
            return finish(func(*args, **kwargs))

        def instance_wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
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
    def __new__(
        cls,
        clsname: str,
        bases: tuple[type, ...],
        attrs: dict[str, Any],
    ) -> ProxyMeta:
        attrs.update(
            {func: ProxyFunc() for func in ("__repr__", "__str__") if func not in attrs}
        )
        proxy_class = cast("type[Proxy]", super().__new__(cls, clsname, bases, attrs))
        functools.update_wrapper(
            proxy_class, proxy_class._wrapped__, assigned=("__doc__",), updated=[]
        )
        return proxy_class


class Proxy(metaclass=ProxyMeta):
    _wrapped__: type = object

    def __init__(self, instance: Any) -> None:
        object.__setattr__(self, "_wrapped__", instance)

    @property  # type: ignore[misc]
    def __class__(self) -> type:
        return type(self)._wrapped__

import functools
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import types

__all__ = [
    "classproperty",
    "conditional",
    "frame_codeinfo",
    "lazy",
    "lazy_classproperty",
    "locked",
    "reset_cached_properties",
    "synchronized",
]


def reset_cached_properties(obj: object) -> None:
    cls = type(obj)
    obj_dict = vars(obj)
    for name in list(obj_dict):
        if isinstance(getattr(cls, name, None), functools.cached_property):
            del obj_dict[name]


def conditional[T](condition: Any, decorator: Callable[[T], T]) -> Callable[[T], T]:
    if condition:
        return decorator
    else:
        return lambda fn: fn


def synchronized(
    lock_attr: str = "_lock",
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:

    def synchronized_lock(func: Callable[..., Any], /) -> Callable[..., Any]:
        @functools.wraps(func)
        def locked(inst: Any, *args: Any, **kwargs: Any) -> Any:
            with getattr(inst, lock_attr):
                return func(inst, *args, **kwargs)

        return locked

    return synchronized_lock


locked = synchronized()


def frame_codeinfo(
    fframe: types.FrameType | None,
    back: int = 0,
) -> tuple[str | None, int | str]:
    try:
        if not fframe:
            return "<unknown>", ""
        for _i in range(back):
            fframe = fframe.f_back
            if fframe is None:
                return "<unknown>", ""
        fname = fframe.f_code.co_filename or "<builtin>"
        lineno = fframe.f_lineno or ""
        return fname, lineno
    except Exception:
        return "<unknown>", ""


class classproperty[T]:
    def __init__(self, fget: Callable[[Any], T]) -> None:
        self.fget = classmethod(fget)

    def __get__(self, cls: Any, owner: type | None = None, /) -> T:
        return self.fget.__get__(None, owner)()

    # A read-only __doc__ over the writeable one every object carries; that
    # is what forwarding the wrapped function's docstring requires.
    @property
    def __doc__(self) -> str | None:  # type: ignore[override]
        return self.fget.__doc__


class lazy_classproperty[T](classproperty[T]):
    def __get__(self, cls: Any, owner: type | None = None, /) -> T:
        val = super().__get__(cls, owner)
        setattr(owner, self.fget.__name__, val)
        return val


class lazy:
    __slots__ = ["_args", "_cached_value", "_func", "_kwargs"]

    def __init__(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        object.__setattr__(self, "_func", func)
        object.__setattr__(self, "_args", args)
        object.__setattr__(self, "_kwargs", kwargs)

    @property
    def _value(self) -> Any:
        if self._func is not None:
            value = self._func(*self._args, **self._kwargs)
            object.__setattr__(self, "_cached_value", value)
            object.__setattr__(self, "_args", None)
            object.__setattr__(self, "_kwargs", None)
            object.__setattr__(self, "_func", None)
        return self._cached_value

    def __getattr__(self, name: str) -> Any:
        if name in lazy.__slots__:
            raise AttributeError(name)
        return getattr(self._value, name)

    def __reduce__(self) -> tuple[Any, tuple[Any]]:
        return (_reconstruct_lazy, (self._value,))

    def __setattr__(self, name: str, value: Any) -> None:
        return setattr(self._value, name, value)

    def __delattr__(self, name: str) -> None:
        return delattr(self._value, name)

    def __repr__(self) -> str:
        return repr(self._value) if self._func is None else object.__repr__(self)

    def __str__(self) -> str:
        return str(self._value)

    def __bytes__(self) -> bytes:
        return bytes(self._value)

    def __format__(self, format_spec: str) -> str:
        return format(self._value, format_spec)

    def __lt__(self, other: Any) -> Any:
        return other > self._value

    def __le__(self, other: Any) -> Any:
        return other >= self._value

    def __eq__(self, other: object) -> Any:
        return other == self._value

    def __ne__(self, other: object) -> Any:
        return other != self._value

    def __gt__(self, other: Any) -> Any:
        return other < self._value

    def __ge__(self, other: Any) -> Any:
        return other <= self._value

    def __hash__(self) -> int:
        return hash(self._value)

    def __bool__(self) -> bool:
        return bool(self._value)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self._value(*args, **kwargs)

    def __len__(self) -> int:
        return len(self._value)

    def __getitem__(self, key: Any) -> Any:
        return self._value[key]

    def __missing__(self, key: Any) -> Any:
        return self._value.__missing__(key)

    def __setitem__(self, key: Any, value: Any) -> None:
        self._value[key] = value

    def __delitem__(self, key: Any) -> None:
        del self._value[key]

    def __iter__(self) -> Any:
        return iter(self._value)

    def __next__(self) -> Any:
        return next(self._value)

    def __reversed__(self) -> Any:
        return reversed(self._value)

    def __contains__(self, key: Any) -> bool:
        return key in self._value

    def __add__(self, other: Any) -> Any:
        return self._value.__add__(other)

    def __sub__(self, other: Any) -> Any:
        return self._value.__sub__(other)

    def __mul__(self, other: Any) -> Any:
        return self._value.__mul__(other)

    def __matmul__(self, other: Any) -> Any:
        return self._value.__matmul__(other)

    def __truediv__(self, other: Any) -> Any:
        return self._value.__truediv__(other)

    def __floordiv__(self, other: Any) -> Any:
        return self._value.__floordiv__(other)

    def __mod__(self, other: Any) -> Any:
        return self._value.__mod__(other)

    def __divmod__(self, other: Any) -> Any:
        return self._value.__divmod__(other)

    def __pow__(self, other: Any, modulo: Any = None) -> Any:
        if modulo is None:
            return self._value**other
        return pow(self._value, other, modulo)

    def __lshift__(self, other: Any) -> Any:
        return self._value.__lshift__(other)

    def __rshift__(self, other: Any) -> Any:
        return self._value.__rshift__(other)

    def __and__(self, other: Any) -> Any:
        return self._value.__and__(other)

    def __xor__(self, other: Any) -> Any:
        return self._value.__xor__(other)

    def __or__(self, other: Any) -> Any:
        return self._value.__or__(other)

    def __radd__(self, other: Any) -> Any:
        return self._value.__radd__(other)

    def __rsub__(self, other: Any) -> Any:
        return self._value.__rsub__(other)

    def __rmul__(self, other: Any) -> Any:
        return self._value.__rmul__(other)

    def __rmatmul__(self, other: Any) -> Any:
        return self._value.__rmatmul__(other)

    def __rtruediv__(self, other: Any) -> Any:
        return self._value.__rtruediv__(other)

    def __rfloordiv__(self, other: Any) -> Any:
        return self._value.__rfloordiv__(other)

    def __rmod__(self, other: Any) -> Any:
        return self._value.__rmod__(other)

    def __rdivmod__(self, other: Any) -> Any:
        return self._value.__rdivmod__(other)

    def __rpow__(self, other: Any) -> Any:
        return self._value.__rpow__(other)

    def __rlshift__(self, other: Any) -> Any:
        return self._value.__rlshift__(other)

    def __rrshift__(self, other: Any) -> Any:
        return self._value.__rrshift__(other)

    def __rand__(self, other: Any) -> Any:
        return self._value.__rand__(other)

    def __rxor__(self, other: Any) -> Any:
        return self._value.__rxor__(other)

    def __ror__(self, other: Any) -> Any:
        return self._value.__ror__(other)

    def __iadd__(self, other: Any) -> Any:
        return self._value.__iadd__(other)

    def __isub__(self, other: Any) -> Any:
        return self._value.__isub__(other)

    def __imul__(self, other: Any) -> Any:
        return self._value.__imul__(other)

    def __imatmul__(self, other: Any) -> Any:
        return self._value.__imatmul__(other)

    def __itruediv__(self, other: Any) -> Any:
        return self._value.__itruediv__(other)

    def __ifloordiv__(self, other: Any) -> Any:
        return self._value.__ifloordiv__(other)

    def __imod__(self, other: Any) -> Any:
        return self._value.__imod__(other)

    def __ipow__(self, other: Any) -> Any:  # type: ignore[misc]
        return self._value.__ipow__(other)

    def __ilshift__(self, other: Any) -> Any:
        return self._value.__ilshift__(other)

    def __irshift__(self, other: Any) -> Any:
        return self._value.__irshift__(other)

    def __iand__(self, other: Any) -> Any:
        return self._value.__iand__(other)

    def __ixor__(self, other: Any) -> Any:
        return self._value.__ixor__(other)

    def __ior__(self, other: Any) -> Any:
        return self._value.__ior__(other)

    def __neg__(self) -> Any:
        return self._value.__neg__()

    def __pos__(self) -> Any:
        return self._value.__pos__()

    def __abs__(self) -> Any:
        return self._value.__abs__()

    def __invert__(self) -> Any:
        return self._value.__invert__()

    def __complex__(self) -> complex:
        return complex(self._value)

    def __int__(self) -> int:
        return int(self._value)

    def __float__(self) -> float:
        return float(self._value)

    def __index__(self) -> int:
        return self._value.__index__()

    def __round__(self, ndigits: Any = None) -> Any:
        return round(self._value, ndigits)

    def __trunc__(self) -> Any:
        return self._value.__trunc__()

    def __floor__(self) -> Any:
        return self._value.__floor__()

    def __ceil__(self) -> Any:
        return self._value.__ceil__()

    def __enter__(self) -> Any:
        return self._value.__enter__()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: types.TracebackType | None,
    ) -> Any:
        return self._value.__exit__(exc_type, exc_value, traceback)

    def __await__(self) -> Any:
        return self._value.__await__()

    def __aiter__(self) -> Any:
        return self._value.__aiter__()

    def __anext__(self) -> Any:
        return self._value.__anext__()

    def __aenter__(self) -> Any:
        return self._value.__aenter__()

    def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: types.TracebackType | None,
    ) -> Any:
        return self._value.__aexit__(exc_type, exc_value, traceback)


def _reconstruct_lazy(value: Any) -> lazy:
    obj = lazy.__new__(lazy)
    object.__setattr__(obj, "_func", None)
    object.__setattr__(obj, "_args", None)
    object.__setattr__(obj, "_kwargs", None)
    object.__setattr__(obj, "_cached_value", value)
    return obj

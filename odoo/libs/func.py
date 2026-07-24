"""Function and decorator utilities, including lazy evaluation."""

import functools
from collections.abc import Callable
from inspect import getsourcefile
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
    """Reset all cached properties on the instance `obj`."""
    cls = type(obj)
    obj_dict = vars(obj)
    for name in list(obj_dict):
        if isinstance(getattr(cls, name, None), functools.cached_property):
            del obj_dict[name]


def conditional[T](condition: Any, decorator: Callable[[T], T]) -> Callable[[T], T]:
    """Apply ``decorator`` only when ``condition`` is truthy.

    Example::

       @conditional(get_config("use_cache"), ormcache)
       def fn():
           pass
    """
    if condition:
        return decorator
    else:
        return lambda fn: fn


def synchronized(
    lock_attr: str = "_lock",
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Build a decorator that serializes method calls under a lock.

    The decorated method holds ``getattr(self, lock_attr)`` (default
    ``"_lock"``) for the duration of each call.
    """

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
    """Return a ``(filename, lineno)`` pair for an ancestor frame.

    :param fframe: starting frame, or ``None``.
    :param back: number of frames to walk back from ``fframe``.
    :return: ``(filename, lineno)`` where ``lineno`` is an ``int`` or ``""``.
    """
    try:
        if not fframe:
            return "<unknown>", ""
        for _i in range(back):
            fframe = fframe.f_back
        try:
            fname = getsourcefile(fframe)
        except TypeError:
            fname = "<builtin>"
        lineno = fframe.f_lineno or ""
        return fname, lineno
    except Exception:
        return "<unknown>", ""


class classproperty[T]:
    """Expose a classmethod as a read-only class-level attribute."""

    def __init__(self, fget: Callable[[Any], T]) -> None:
        """Wrap ``fget`` as a classmethod getter."""
        self.fget = classmethod(fget)

    def __get__(self, cls: Any, owner: type | None = None, /) -> T:
        """Return the class-property value by invoking the getter."""
        return self.fget.__get__(None, owner)()

    @property
    def __doc__(self) -> str | None:
        """Return the docstring of the wrapped getter."""
        return self.fget.__doc__


class lazy_classproperty[T](classproperty[T]):
    """A classproperty that caches its value on the owner class on first access."""

    def __get__(self, cls: Any, owner: type | None = None, /) -> T:
        """Compute the value, cache it on the owner class, and return it."""
        val = super().__get__(cls, owner)
        setattr(owner, self.fget.__name__, val)
        return val


class lazy:
    """A proxy to the (memoized) result of a lazy evaluation.

    .. code-block::

        foo = lazy(func, arg)           # func(arg) is not called yet
        bar = foo + 1                   # eval func(arg) and add 1
        baz = foo + 2                   # use result of func(arg) and add 2
    """

    __slots__ = ["_args", "_cached_value", "_func", "_kwargs"]

    def __init__(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        """Store the callable and its arguments for later evaluation."""
        # bypass own __setattr__
        object.__setattr__(self, "_func", func)
        object.__setattr__(self, "_args", args)
        object.__setattr__(self, "_kwargs", kwargs)

    @property
    def _value(self) -> Any:
        if self._func is not None:
            value = self._func(*self._args, **self._kwargs)
            # Publish the result before clearing ``_func``: ``_func is None`` is
            # the "already evaluated" flag, so ``_cached_value`` must be set
            # first or a concurrent reader (or a reader that raced in during
            # evaluation) sees the flag flipped while the slot is still unset.
            object.__setattr__(self, "_cached_value", value)
            object.__setattr__(self, "_args", None)
            object.__setattr__(self, "_kwargs", None)
            object.__setattr__(self, "_func", None)
        return self._cached_value

    def __getattr__(self, name: str) -> Any:
        """Delegate attribute access to the evaluated value."""
        # Own slots are looked up via __getattribute__; reaching __getattr__ for
        # one means it is genuinely unset (e.g. ``_cached_value`` before the
        # first evaluation, or during unpickling before __init__ runs).  Raise
        # immediately instead of delegating to ``self._value``, which would read
        # the same unset slot and recurse forever (copy/pickle hit this).
        if name in lazy.__slots__:
            raise AttributeError(name)
        return getattr(self._value, name)

    def __reduce__(self) -> tuple[Any, tuple[Any]]:
        """Pickle/copy the evaluated value rather than the callable + args."""
        # The callable and its arguments are frequently unpicklable, and routing
        # pickle's protocol lookups through ``__getattr__`` would force-evaluate
        # (or recurse).  Reconstruct a pre-evaluated ``lazy`` so the proxy type
        # survives a round-trip.
        return (_reconstruct_lazy, (self._value,))

    def __setattr__(self, name: str, value: Any) -> None:
        """Delegate attribute assignment to the evaluated value."""
        return setattr(self._value, name, value)

    def __delattr__(self, name: str) -> None:
        """Delegate attribute deletion to the evaluated value."""
        return delattr(self._value, name)

    def __repr__(self) -> str:
        """Return the representation of the value, if already evaluated."""
        return repr(self._value) if self._func is None else object.__repr__(self)

    def __str__(self) -> str:
        """Return the string form of the evaluated value."""
        return str(self._value)

    def __bytes__(self) -> bytes:
        """Return the bytes form of the evaluated value."""
        return bytes(self._value)

    def __format__(self, format_spec: str) -> str:
        """Format the evaluated value with ``format_spec``."""
        return format(self._value, format_spec)

    def __lt__(self, other: Any) -> Any:
        """Return whether the value is less than ``other``."""
        return other > self._value

    def __le__(self, other: Any) -> Any:
        """Return whether the value is less than or equal to ``other``."""
        return other >= self._value

    def __eq__(self, other: Any) -> Any:
        """Return whether the value equals ``other``."""
        return other == self._value

    def __ne__(self, other: Any) -> Any:
        """Return whether the value differs from ``other``."""
        return other != self._value

    def __gt__(self, other: Any) -> Any:
        """Return whether the value is greater than ``other``."""
        return other < self._value

    def __ge__(self, other: Any) -> Any:
        """Return whether the value is greater than or equal to ``other``."""
        return other <= self._value

    def __hash__(self) -> int:
        """Return the hash of the evaluated value."""
        return hash(self._value)

    def __bool__(self) -> bool:
        """Return the truthiness of the evaluated value."""
        return bool(self._value)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Call the evaluated value with the given arguments."""
        return self._value(*args, **kwargs)

    def __len__(self) -> int:
        """Return the length of the evaluated value."""
        return len(self._value)

    def __getitem__(self, key: Any) -> Any:
        """Return the item of the evaluated value at ``key``."""
        return self._value[key]

    def __missing__(self, key: Any) -> Any:
        """Delegate missing-key handling to the evaluated value."""
        return self._value.__missing__(key)

    def __setitem__(self, key: Any, value: Any) -> None:
        """Set the item of the evaluated value at ``key``."""
        self._value[key] = value

    def __delitem__(self, key: Any) -> None:
        """Delete the item of the evaluated value at ``key``."""
        del self._value[key]

    def __iter__(self) -> Any:
        """Return an iterator over the evaluated value."""
        return iter(self._value)

    def __next__(self) -> Any:
        """Return the next item when the evaluated value is an iterator."""
        return next(self._value)

    def __reversed__(self) -> Any:
        """Return a reverse iterator over the evaluated value."""
        return reversed(self._value)

    def __contains__(self, key: Any) -> bool:
        """Return whether ``key`` is contained in the evaluated value."""
        return key in self._value

    def __add__(self, other: Any) -> Any:
        """Return ``self._value + other``."""
        return self._value.__add__(other)

    def __sub__(self, other: Any) -> Any:
        """Return ``self._value - other``."""
        return self._value.__sub__(other)

    def __mul__(self, other: Any) -> Any:
        """Return ``self._value * other``."""
        return self._value.__mul__(other)

    def __matmul__(self, other: Any) -> Any:
        """Return ``self._value @ other``."""
        return self._value.__matmul__(other)

    def __truediv__(self, other: Any) -> Any:
        """Return ``self._value / other``."""
        return self._value.__truediv__(other)

    def __floordiv__(self, other: Any) -> Any:
        """Return ``self._value // other``."""
        return self._value.__floordiv__(other)

    def __mod__(self, other: Any) -> Any:
        """Return ``self._value % other``."""
        return self._value.__mod__(other)

    def __divmod__(self, other: Any) -> Any:
        """Return ``divmod(self._value, other)``."""
        return self._value.__divmod__(other)

    def __pow__(self, other: Any, modulo: Any = None) -> Any:
        """Return ``self._value ** other`` (or the 3-arg ``pow`` with ``modulo``)."""
        if modulo is None:
            return self._value**other
        return pow(self._value, other, modulo)

    def __lshift__(self, other: Any) -> Any:
        """Return ``self._value << other``."""
        return self._value.__lshift__(other)

    def __rshift__(self, other: Any) -> Any:
        """Return ``self._value >> other``."""
        return self._value.__rshift__(other)

    def __and__(self, other: Any) -> Any:
        """Return ``self._value & other``."""
        return self._value.__and__(other)

    def __xor__(self, other: Any) -> Any:
        """Return ``self._value ^ other``."""
        return self._value.__xor__(other)

    def __or__(self, other: Any) -> Any:
        """Return ``self._value | other``."""
        return self._value.__or__(other)

    def __radd__(self, other: Any) -> Any:
        """Return ``other + self._value``."""
        return self._value.__radd__(other)

    def __rsub__(self, other: Any) -> Any:
        """Return ``other - self._value``."""
        return self._value.__rsub__(other)

    def __rmul__(self, other: Any) -> Any:
        """Return ``other * self._value``."""
        return self._value.__rmul__(other)

    def __rmatmul__(self, other: Any) -> Any:
        """Return ``other @ self._value``."""
        return self._value.__rmatmul__(other)

    def __rtruediv__(self, other: Any) -> Any:
        """Return ``other / self._value``."""
        return self._value.__rtruediv__(other)

    def __rfloordiv__(self, other: Any) -> Any:
        """Return ``other // self._value``."""
        return self._value.__rfloordiv__(other)

    def __rmod__(self, other: Any) -> Any:
        """Return ``other % self._value``."""
        return self._value.__rmod__(other)

    def __rdivmod__(self, other: Any) -> Any:
        """Return ``divmod(other, self._value)``."""
        return self._value.__rdivmod__(other)

    def __rpow__(self, other: Any) -> Any:
        """Return ``other ** self._value``."""
        return self._value.__rpow__(other)

    def __rlshift__(self, other: Any) -> Any:
        """Return ``other << self._value``."""
        return self._value.__rlshift__(other)

    def __rrshift__(self, other: Any) -> Any:
        """Return ``other >> self._value``."""
        return self._value.__rrshift__(other)

    def __rand__(self, other: Any) -> Any:
        """Return ``other & self._value``."""
        return self._value.__rand__(other)

    def __rxor__(self, other: Any) -> Any:
        """Return ``other ^ self._value``."""
        return self._value.__rxor__(other)

    def __ror__(self, other: Any) -> Any:
        """Return ``other | self._value``."""
        return self._value.__ror__(other)

    def __iadd__(self, other: Any) -> Any:
        """Return the in-place addition with ``other``."""
        return self._value.__iadd__(other)

    def __isub__(self, other: Any) -> Any:
        """Return the in-place subtraction with ``other``."""
        return self._value.__isub__(other)

    def __imul__(self, other: Any) -> Any:
        """Return the in-place multiplication with ``other``."""
        return self._value.__imul__(other)

    def __imatmul__(self, other: Any) -> Any:
        """Return the in-place matrix multiplication with ``other``."""
        return self._value.__imatmul__(other)

    def __itruediv__(self, other: Any) -> Any:
        """Return the in-place true division with ``other``."""
        return self._value.__itruediv__(other)

    def __ifloordiv__(self, other: Any) -> Any:
        """Return the in-place floor division with ``other``."""
        return self._value.__ifloordiv__(other)

    def __imod__(self, other: Any) -> Any:
        """Return the in-place modulo with ``other``."""
        return self._value.__imod__(other)

    def __ipow__(self, other: Any) -> Any:
        """Return the in-place exponentiation with ``other``."""
        return self._value.__ipow__(other)

    def __ilshift__(self, other: Any) -> Any:
        """Return the in-place left shift with ``other``."""
        return self._value.__ilshift__(other)

    def __irshift__(self, other: Any) -> Any:
        """Return the in-place right shift with ``other``."""
        return self._value.__irshift__(other)

    def __iand__(self, other: Any) -> Any:
        """Return the in-place bitwise-and with ``other``."""
        return self._value.__iand__(other)

    def __ixor__(self, other: Any) -> Any:
        """Return the in-place bitwise-xor with ``other``."""
        return self._value.__ixor__(other)

    def __ior__(self, other: Any) -> Any:
        """Return the in-place bitwise-or with ``other``."""
        return self._value.__ior__(other)

    def __neg__(self) -> Any:
        """Return the negation of the evaluated value."""
        return self._value.__neg__()

    def __pos__(self) -> Any:
        """Return the unary plus of the evaluated value."""
        return self._value.__pos__()

    def __abs__(self) -> Any:
        """Return the absolute value of the evaluated value."""
        return self._value.__abs__()

    def __invert__(self) -> Any:
        """Return the bitwise inversion of the evaluated value."""
        return self._value.__invert__()

    def __complex__(self) -> complex:
        """Return the evaluated value as a ``complex``."""
        return complex(self._value)

    def __int__(self) -> int:
        """Return the evaluated value as an ``int``."""
        return int(self._value)

    def __float__(self) -> float:
        """Return the evaluated value as a ``float``."""
        return float(self._value)

    def __index__(self) -> int:
        """Return the evaluated value as an index ``int``."""
        return self._value.__index__()

    def __round__(self, ndigits: Any = None) -> Any:
        """Return the evaluated value rounded to ``ndigits`` (``round(x, n)``)."""
        return round(self._value, ndigits)

    def __trunc__(self) -> Any:
        """Return the truncated evaluated value."""
        return self._value.__trunc__()

    def __floor__(self) -> Any:
        """Return the floor of the evaluated value."""
        return self._value.__floor__()

    def __ceil__(self) -> Any:
        """Return the ceiling of the evaluated value."""
        return self._value.__ceil__()

    def __enter__(self) -> Any:
        """Enter the evaluated value as a context manager."""
        return self._value.__enter__()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: types.TracebackType | None,
    ) -> Any:
        """Exit the evaluated value's context manager."""
        return self._value.__exit__(exc_type, exc_value, traceback)

    def __await__(self) -> Any:
        """Return the awaitable of the evaluated value."""
        return self._value.__await__()

    def __aiter__(self) -> Any:
        """Return an async iterator over the evaluated value."""
        return self._value.__aiter__()

    def __anext__(self) -> Any:
        """Return the next item from the evaluated async iterator."""
        return self._value.__anext__()

    def __aenter__(self) -> Any:
        """Enter the evaluated value as an async context manager."""
        return self._value.__aenter__()

    def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: types.TracebackType | None,
    ) -> Any:
        """Exit the evaluated value's async context manager."""
        return self._value.__aexit__(exc_type, exc_value, traceback)


def _reconstruct_lazy(value: Any) -> lazy:
    """Rebuild an already-evaluated :class:`lazy` (used by ``lazy.__reduce__``)."""
    obj = lazy.__new__(lazy)
    object.__setattr__(obj, "_func", None)
    object.__setattr__(obj, "_args", None)
    object.__setattr__(obj, "_kwargs", None)
    object.__setattr__(obj, "_cached_value", value)
    return obj

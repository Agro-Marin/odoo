__all__ = ["freehash", "frozendict"]

from collections.abc import Iterable, Mapping
from typing import Any


def freehash(arg: Any) -> int:
    try:
        return hash(arg)
    except Exception:
        if isinstance(arg, Mapping):
            return hash(frozendict(arg))
        elif isinstance(arg, Iterable):
            return hash(frozenset(freehash(item) for item in arg))
        else:
            return id(arg)


class frozendict[K, T](dict[K, T]):
    __slots__ = ("_hash",)

    def __delitem__(self, key: K) -> None:
        msg = "'__delitem__' not supported on frozendict"
        raise NotImplementedError(msg)

    def __setitem__(self, key: K, val: T) -> None:
        msg = "'__setitem__' not supported on frozendict"
        raise NotImplementedError(msg)

    def clear(self) -> None:
        msg = "'clear' not supported on frozendict"
        raise NotImplementedError(msg)

    def pop(self, key: K, default: T | None = None) -> T:
        msg = "'pop' not supported on frozendict"
        raise NotImplementedError(msg)

    def popitem(self) -> tuple[K, T]:
        msg = "'popitem' not supported on frozendict"
        raise NotImplementedError(msg)

    def setdefault(self, key: K, default: T | None = None) -> T:
        msg = "'setdefault' not supported on frozendict"
        raise NotImplementedError(msg)

    def update(self, *args: Any, **kwargs: Any) -> None:
        msg = "'update' not supported on frozendict"
        raise NotImplementedError(msg)

    def __ior__(self, other: Any) -> None:
        msg = "'|=' not supported on frozendict"
        raise NotImplementedError(msg)

    def __reduce__(self) -> tuple[Any, tuple[type, dict[K, T]]]:
        return (_rebuild_frozendict, (type(self), dict(self)))

    def __hash__(self) -> int:
        try:
            return self._hash
        except AttributeError:
            h = hash(frozenset((key, freehash(val)) for key, val in self.items()))
            object.__setattr__(self, "_hash", h)
            return h


def _rebuild_frozendict[K, T](cls: type, items: dict[K, T]) -> Any:
    obj = dict.__new__(cls)
    dict.update(obj, items)
    return obj

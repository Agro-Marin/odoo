__all__ = ["freehash", "frozendict"]

from collections.abc import Iterable, Mapping
from typing import Any, NoReturn


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

    # Declared for the checker; `__slots__` alone gives it no type, and the
    # AttributeError branch in __hash__ depends on the slot starting unset.
    _hash: int

    # Three overrides below are deliberately incompatible with `dict`, and that
    # incompatibility IS the class: a frozen mapping cannot honour a mutable
    # supertype's contract. `pop` cannot match dict's three overloads with one
    # always-raising signature; `__ior__` must disagree with `__or__`, which
    # dict requires to agree; and `__hash__` reverses `dict.__hash__ = None`,
    # which is the entire reason to have this type. Each is pinned narrowly so
    # a fourth, accidental one still fails.

    def __delitem__(self, key: K) -> NoReturn:
        msg = "'__delitem__' not supported on frozendict"
        raise NotImplementedError(msg)

    def __setitem__(self, key: K, val: T) -> NoReturn:
        msg = "'__setitem__' not supported on frozendict"
        raise NotImplementedError(msg)

    def clear(self) -> NoReturn:
        msg = "'clear' not supported on frozendict"
        raise NotImplementedError(msg)

    def pop(self, key: K, default: T | None = None) -> NoReturn:  # type: ignore[override]
        msg = "'pop' not supported on frozendict"
        raise NotImplementedError(msg)

    def popitem(self) -> NoReturn:
        msg = "'popitem' not supported on frozendict"
        raise NotImplementedError(msg)

    def setdefault(self, key: K, default: T | None = None) -> NoReturn:
        msg = "'setdefault' not supported on frozendict"
        raise NotImplementedError(msg)

    def update(self, *args: Any, **kwargs: Any) -> NoReturn:
        msg = "'update' not supported on frozendict"
        raise NotImplementedError(msg)

    def __ior__(self, other: Any) -> NoReturn:  # type: ignore[misc]
        msg = "'|=' not supported on frozendict"
        raise NotImplementedError(msg)

    def __reduce__(self) -> tuple[Any, tuple[type, dict[K, T]]]:
        return (_rebuild_frozendict, (type(self), dict(self)))

    def __hash__(self) -> int:  # type: ignore[override]
        try:
            return self._hash
        except AttributeError:
            h = hash(frozenset((key, freehash(val)) for key, val in self.items()))
            object.__setattr__(self, "_hash", h)
            return h


def _rebuild_frozendict[K, T](cls: type, items: dict[K, T]) -> Any:
    obj: dict[K, T] = dict.__new__(cls)
    dict.update(obj, items)
    return obj

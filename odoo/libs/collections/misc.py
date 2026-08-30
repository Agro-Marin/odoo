__all__ = ["Collector", "ReversedIterable", "StackMap"]

import itertools
import typing
from collections.abc import Iterable, Iterator, MutableMapping, Reversible
from typing import Any


class Collector[K, T](dict[K, tuple[T, ...]]):
    __slots__ = ()

    def __init__(self, mapping: Any = (), /, **kwargs: Iterable[T]) -> None:
        super().__init__()
        self.update(mapping, **kwargs)

    def update(self, mapping: Any = (), /, **kwargs: Iterable[T]) -> None:  # type: ignore[override]
        items = mapping.items() if hasattr(mapping, "items") else mapping
        for key, val in itertools.chain(items, kwargs.items()):
            self[key] = val

    def setdefault(self, key: K, default: Iterable[T] = (), /) -> tuple[T, ...]:  # type: ignore[override]
        if key not in self:
            self[key] = default
        return self[key]

    def __getitem__(self, key: K) -> tuple[T, ...]:
        return dict.get(self, key, ())

    @typing.overload  # type: ignore[override]
    def get(self, key: K, /) -> tuple[T, ...]: ...
    @typing.overload
    def get[D](self, key: K, /, default: D) -> tuple[T, ...] | D: ...

    def get(self, key: K, /, default: typing.Any = ()) -> typing.Any:
        return dict.get(self, key, default)

    @typing.overload
    def pop(self, key: K, /) -> tuple[T, ...]: ...
    @typing.overload
    def pop[D](self, key: K, /, default: D) -> tuple[T, ...] | D: ...

    def pop(self, key: K, /, default: typing.Any = ()) -> typing.Any:
        return dict.pop(self, key, default)

    def __setitem__(self, key: K, val: Iterable[T]) -> None:
        val = tuple(val)
        if val:
            super().__setitem__(key, val)
        else:
            super().pop(key, None)

    def add(self, key: K, val: T) -> None:
        vals = self[key]
        if val not in vals:
            self[key] = vals + (val,)

    def discard_keys_and_values(self, excludes: Iterable[K]) -> None:
        excluded = frozenset(excludes)
        for key in excluded:
            self.pop(key, None)
        for key, vals in list(self.items()):
            if not excluded.isdisjoint(vals):
                self[key] = tuple(val for val in vals if val not in excluded)


class StackMap[K, T](MutableMapping[K, T]):
    __slots__ = ["_maps"]

    def __init__(self, m: MutableMapping[K, T] | None = None) -> None:
        self._maps: list[MutableMapping[K, T]] = [] if m is None else [m]

    def __getitem__(self, key: K) -> T:
        for mapping in reversed(self._maps):
            try:
                return mapping[key]
            except KeyError:
                pass
        raise KeyError(key)

    def __setitem__(self, key: K, val: T) -> None:
        self._maps[-1][key] = val

    def __delitem__(self, key: K) -> None:
        del self._maps[-1][key]

    def _unique_keys(self) -> dict[K, None]:
        return dict.fromkeys(key for mapping in self._maps for key in mapping)

    def __iter__(self) -> Iterator[K]:
        return iter(self._unique_keys())

    def __len__(self) -> int:
        return len(self._unique_keys())

    def __str__(self) -> str:
        return f"<StackMap {self._maps}>"

    def pushmap(self, m: MutableMapping[K, T] | None = None) -> None:
        self._maps.append({} if m is None else m)

    def popmap(self) -> MutableMapping[K, T]:
        return self._maps.pop()


class ReversedIterable[T](Reversible[T]):
    __slots__ = ["iterable"]

    def __init__(self, iterable: Reversible[T]) -> None:
        self.iterable = iterable

    def __iter__(self) -> Iterator[T]:
        return reversed(self.iterable)

    def __reversed__(self) -> Iterator[T]:
        return iter(self.iterable)

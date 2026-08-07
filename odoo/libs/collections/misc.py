__all__ = ["Collector", "ReversedIterable", "StackMap"]

from collections.abc import Iterable, Iterator, MutableMapping, Reversible


class Collector[K, T](dict[K, tuple[T, ...]]):
    __slots__ = ()

    def __getitem__(self, key: K) -> tuple[T, ...]:
        return self.get(key, ())

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

    def __iter__(self) -> Iterator[K]:
        return iter({key for mapping in self._maps for key in mapping})

    def __len__(self) -> int:
        return len({key for mapping in self._maps for key in mapping})

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

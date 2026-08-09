__all__ = ["groupby", "partition", "unique"]

from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator
from typing import Any, overload


@overload
def groupby[T](iterable: Iterable[T]) -> Iterable[tuple[T, list[T]]]: ...


@overload
def groupby[T, K](
    iterable: Iterable[T], key: Callable[[T], K]
) -> Iterable[tuple[K, list[T]]]: ...


def groupby[T](
    iterable: Iterable[T], key: Callable[[T], Any] = lambda arg: arg
) -> Iterable[tuple[Any, list[T]]]:
    groups: defaultdict[Any, list[T]] = defaultdict(list)
    for elem in iterable:
        groups[key(elem)].append(elem)
    return groups.items()


def unique[T](it: Iterable[T]) -> Iterator[T]:
    seen: set[T] = set()
    for e in it:
        if e not in seen:
            seen.add(e)
            yield e


def partition[T](
    pred: Callable[[T], bool], elems: Iterable[T]
) -> tuple[list[T], list[T]]:
    yes: list[T] = []
    nos: list[T] = []
    for elem in elems:
        (yes if pred(elem) else nos).append(elem)
    return yes, nos

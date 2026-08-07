__all__ = ["groupby", "partition", "unique"]

from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator


def groupby[T, K](
    iterable: Iterable[T], key: Callable[[T], K] = lambda arg: arg
) -> Iterable[tuple[K, list[T]]]:
    groups: defaultdict[K, list[T]] = defaultdict(list)
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

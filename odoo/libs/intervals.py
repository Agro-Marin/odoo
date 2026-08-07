__all__ = ["Intervals", "intervals_overlap", "invert_intervals"]

import itertools
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from collections.abc import Set as AbstractSet


def _boundaries[T](
    intervals: Intervals[T] | Iterable[tuple[T, T, AbstractSet]],
    opening: str,
    closing: str,
) -> Iterator[tuple[T, str, AbstractSet]]:
    for start, stop, recs in intervals:
        if start < stop:
            yield (start, opening, recs)
            yield (stop, closing, recs)


class Intervals[T]:
    def __init__(
        self,
        intervals: Iterable[tuple[T, T, AbstractSet]] | None = None,
        *,
        keep_distinct: bool = False,
    ) -> None:
        self._items: list[tuple[T, T, AbstractSet]] = []
        self._keep_distinct = keep_distinct
        if intervals:
            append = self._items.append
            starts: list[T] = []
            items: AbstractSet | None = None
            if self._keep_distinct:
                boundaries = sorted(
                    _boundaries(sorted(intervals), "start", "stop"),
                    key=lambda i: i[0],
                )
            else:
                boundaries = sorted(_boundaries(intervals, "start", "stop"))
            for value, flag, value_items in boundaries:
                if flag == "start":
                    starts.append(value)
                    if items is None:
                        items = value_items
                    else:
                        items = items.union(value_items)
                else:
                    start = starts.pop()
                    if not starts:
                        append((start, value, items))
                        items = None

    def __bool__(self) -> bool:
        return bool(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self) -> Iterator[tuple[T, T, AbstractSet]]:
        return iter(self._items)

    def __reversed__(self) -> Iterator[tuple[T, T, AbstractSet]]:
        return reversed(self._items)

    def __or__(self, other: Intervals[T]) -> Intervals[T]:
        return Intervals(
            itertools.chain(self._items, other._items),
            keep_distinct=self._keep_distinct,
        )

    def __and__(
        self, other: Intervals[T] | Iterable[tuple[T, T, AbstractSet]]
    ) -> Intervals[T]:
        return self._merge(other, difference=False)

    def __sub__(
        self, other: Intervals[T] | Iterable[tuple[T, T, AbstractSet]]
    ) -> Intervals[T]:
        return self._merge(other, difference=True)

    def _merge(
        self,
        other: Intervals[T] | Iterable[tuple[T, T, AbstractSet]],
        difference: bool,
    ) -> Intervals[T]:
        result = Intervals(keep_distinct=self._keep_distinct)
        append = result._items.append

        bounds1 = _boundaries(self, "start", "stop")
        bounds2 = _boundaries(
            Intervals(other, keep_distinct=self._keep_distinct),
            "switch",
            "switch",
        )

        start = None
        recs1 = None
        enabled = difference
        if self._keep_distinct:
            bounds = sorted(itertools.chain(bounds1, bounds2), key=lambda i: i[0])
        else:
            bounds = sorted(itertools.chain(bounds1, bounds2))
        for value, flag, recs in bounds:
            if flag == "start":
                start = value
                recs1 = recs
            elif flag == "stop":
                if enabled and start < value:
                    append((start, value, recs1))
                start = None
            else:
                if not enabled and start is not None:
                    start = value
                if enabled and start is not None and start < value:
                    append((start, value, recs1))
                enabled = not enabled

        return result


def intervals_overlap[T](interval_a: tuple[T, T], interval_b: tuple[T, T]) -> bool:
    start_a, stop_a = interval_a
    start_b, stop_b = interval_b
    return start_a < stop_b and stop_a > start_b


def invert_intervals[T](
    intervals: Iterable[tuple[T, T]], first_start: T, last_stop: T
) -> list[tuple[T, T]]:
    items = []
    prev_stop = first_start
    for start, stop in sorted(intervals):
        if start > last_stop:
            break
        if prev_stop < start:
            items.append((prev_stop, start))
        prev_stop = max(prev_stop, stop)
        if stop >= last_stop:
            break
    if prev_stop < last_stop:
        items.append((prev_stop, last_stop))
    return [
        (start, stop)
        for start, stop, _ in Intervals([(start, stop, set()) for start, stop in items])
    ]

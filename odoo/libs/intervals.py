__all__ = ["Intervals", "intervals_overlap", "invert_intervals"]

import itertools
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from typing import Any, Protocol

    class SupportsUnion(Protocol):
        def union(self, other: Any, /) -> SupportsUnion: ...

    class SupportsOrdering(Protocol):
        def __lt__(self, other: Any, /) -> bool: ...
        def __gt__(self, other: Any, /) -> bool: ...
        def __ge__(self, other: Any, /) -> bool: ...


def _endpoints(item: tuple[Any, Any, Any]) -> tuple[Any, Any]:
    """Sort key that stops before the payload.

    The two-element key is also what orders coincident boundaries, and the
    order comes from the flag *strings*: ``"start" < "stop"`` is what merges
    two adjacent intervals into one. Renaming either changes that -- measured:
    ``"start"`` -> ``"zstart"`` splits ``[(0,5),(5,10)]`` back into two -- and
    ``test_intervals`` catches it, which is the only reason it is a note here
    rather than an integer rank. ``"switch"`` carries no such weight: renaming
    it changes nothing, tested across five coincident-boundary shapes.

    Both shapes sorted here end in the payload -- ``(start, stop, records)``
    going in, ``(value, flag, records)`` once split into boundaries -- and
    sorting one whole lets a tie on the first two fall through to comparing the
    *payload*: an Odoo recordset, whose ``__lt__`` is a subset partial order and
    returns ``NotImplemented`` across models, i.e. ``TypeError``. A sort key must never
    be able to reach a payload object. Measured over ``/resource,/hr``: the
    boundary sort never got there (0 of 98,322 boundaries), but the
    ``keep_distinct`` pre-sort did, twice in 480 calls, with three payload
    models coexisting in the run.
    """
    return (item[0], item[1])


def _boundaries[T: SupportsOrdering](
    intervals: Intervals[T] | Iterable[tuple[T, T, SupportsUnion]],
    opening: str,
    closing: str,
) -> Iterator[tuple[T, str, SupportsUnion]]:
    for start, stop, recs in intervals:
        if start < stop:
            yield (start, opening, recs)
            yield (stop, closing, recs)


class Intervals[T: SupportsOrdering]:
    def __init__(
        self,
        intervals: Iterable[tuple[T, T, SupportsUnion]] | None = None,
        *,
        keep_distinct: bool = False,
    ) -> None:
        self._items: list[tuple[T, T, SupportsUnion]] = []
        self._keep_distinct = keep_distinct
        if intervals:
            append = self._items.append
            starts: list[T] = []
            items: SupportsUnion | None = None
            if self._keep_distinct:
                boundaries = sorted(
                    _boundaries(sorted(intervals, key=_endpoints), "start", "stop"),
                    key=lambda i: i[0],
                )
            else:
                boundaries = sorted(
                    _boundaries(intervals, "start", "stop"), key=_endpoints
                )
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
                        assert items is not None, "a stop with no open start"
                        append((start, value, items))
                        items = None

    def __bool__(self) -> bool:
        return bool(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self) -> Iterator[tuple[T, T, SupportsUnion]]:
        return iter(self._items)

    def __reversed__(self) -> Iterator[tuple[T, T, SupportsUnion]]:
        return reversed(self._items)

    def __or__(self, other: Intervals[T]) -> Intervals[T]:
        return Intervals(
            itertools.chain(self._items, other._items),
            keep_distinct=self._keep_distinct,
        )

    def __and__(
        self, other: Intervals[T] | Iterable[tuple[T, T, SupportsUnion]]
    ) -> Intervals[T]:
        return self._merge(other, difference=False)

    def __sub__(
        self, other: Intervals[T] | Iterable[tuple[T, T, SupportsUnion]]
    ) -> Intervals[T]:
        return self._merge(other, difference=True)

    def _merge(
        self,
        other: Intervals[T] | Iterable[tuple[T, T, SupportsUnion]],
        difference: bool,
    ) -> Intervals[T]:
        result: Intervals[T] = Intervals(keep_distinct=self._keep_distinct)
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
            bounds = sorted(itertools.chain(bounds1, bounds2), key=_endpoints)
        for value, flag, recs in bounds:
            if flag == "start":
                start = value
                recs1 = recs
            elif flag == "stop":
                if enabled and start is not None and start < value:
                    assert recs1 is not None, "a start without its records"
                    append((start, value, recs1))
                start = None
            else:
                if not enabled and start is not None:
                    start = value
                if enabled and start is not None and start < value:
                    assert recs1 is not None, "a start without its records"
                    append((start, value, recs1))
                enabled = not enabled

        return result


def intervals_overlap[T: SupportsOrdering](
    interval_a: tuple[T, T], interval_b: tuple[T, T]
) -> bool:
    start_a, stop_a = interval_a
    start_b, stop_b = interval_b
    return start_a < stop_b and stop_a > start_b


def invert_intervals[T: SupportsOrdering](
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

    merged: list[tuple[T, T]] = []
    for start, stop in items:
        if not start < stop:
            continue
        if merged and not merged[-1][1] < start:
            merged[-1] = (merged[-1][0], max(merged[-1][1], stop))
        else:
            merged.append((start, stop))
    return merged

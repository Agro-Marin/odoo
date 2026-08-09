__all__ = ["split_every"]

import warnings
from itertools import islice
from typing import TYPE_CHECKING, Any, overload

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterable, Iterator


def _split_every[T](
    n: int,
    iterable: Iterable[T],
    piece_maker: Callable[[Iterable[T]], Any] = tuple,
) -> Iterator[Any]:
    iterator = iter(iterable)
    piece = piece_maker(islice(iterator, n))
    while piece:
        yield piece
        piece = piece_maker(islice(iterator, n))


@overload
def split_every[T](n: int, iterable: Iterable[T]) -> Iterator[tuple[T, ...]]: ...


@overload
def split_every[T](
    n: int, iterable: Iterable[T], piece_maker: type[Collection[T]]
) -> Iterator[Collection[T]]: ...


@overload
def split_every[T, P](
    n: int, iterable: Iterable[T], piece_maker: Callable[[Iterable[T]], P]
) -> Iterator[P]: ...


def split_every[T](
    n: int,
    iterable: Iterable[T],
    piece_maker: Callable[[Iterable[T]], Any] = tuple,
) -> Iterator[Any]:
    warnings.warn(
        "split_every() is deprecated, use itertools.batched(iterable, n) instead. "
        "Note the swapped argument order.",
        DeprecationWarning,
        stacklevel=2,
    )
    return _split_every(n, iterable, piece_maker)

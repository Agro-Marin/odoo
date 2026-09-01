from __future__ import annotations

import math
import random
import typing

if typing.TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = ["bound", "bounds", "delay"]


def bound(attempt: int, *, base: float, cap: float) -> float:
    if attempt < 1:
        raise ValueError(f"attempt is 1-based, got {attempt}")
    if base <= 0.0:
        raise ValueError(f"base must be positive, got {base}")
    if cap < base:
        raise ValueError(
            f"cap ({cap}) is below base ({base}), which flattens the curve: "
            f"every attempt would draw from the same interval"
        )
    doublings = attempt - 1
    if doublings >= math.ceil(math.log2(cap / base)):
        # Short-circuit rather than clamp the product: a caller still
        # retrying after ~1024 attempts overflows the float before `min`
        # ever sees it, out of the retry path that exists to survive that.
        return cap
    return min(base * 2.0**doublings, cap)


def bounds(attempts: int, *, base: float, cap: float) -> Iterator[float]:
    for attempt in range(1, attempts + 1):
        yield bound(attempt, base=base, cap=cap)


def delay(
    attempt: int,
    *,
    base: float,
    cap: float,
    rng: random.Random | None = None,
) -> float:
    ceiling = bound(attempt, base=base, cap=cap)
    return (rng or random).uniform(0.0, ceiling)

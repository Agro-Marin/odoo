"""Capped exponential backoff with full jitter.

Retry loops that contend for the same resource must spread their retries apart,
or every contender re-collides on the next round at the same rate as the first.
That is what an *exponential* curve buys: the probability of a repeat collision
decays per attempt. Jitter buys the other half -- without it, N contenders that
failed together wake together.

The delay for a 1-based ``attempt`` is drawn uniformly from
``[0, min(base * 2**(attempt - 1), cap)]`` -- the "full jitter" schedule. ``base``
is therefore the bound for the *first* retry, which is what makes a call site
readable: ``base=0.2, cap=2.0`` says "start at 0.2s, double, never exceed 2s".

This module exists because the schedule was open-coded four times and got it
wrong twice, in the same shape both times::

    random.uniform(0.0, min(2 ** attempt, 2.0))     # attempt starts at 1

``2 ** 1`` already equals the 2.0 cap, so the cap won on every iteration and the
curve was flat: every retry drew from the same ``uniform(0, 2.0)``. The growth
term was decorative. Both sites -- ``service/transaction.py``'s ``retrying()``
and ``ir_job``'s concurrency replay -- were the fork's two most contended retry
loops, and neither had a test that looked at the *schedule* rather than at a
single delay. :func:`bounds` exists so that test is one line.
"""

from __future__ import annotations

import random
import typing

if typing.TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = ["bound", "bounds", "delay"]


def bound(attempt: int, *, base: float, cap: float) -> float:
    """Return the delay ceiling for ``attempt``.

    :param attempt: 1-based retry number; ``1`` is the first retry.
    :param base: ceiling for the first retry, doubled on each subsequent one.
    :param cap: value the ceiling never exceeds.
    :return: ``min(base * 2 ** (attempt - 1), cap)``.
    :raises ValueError: if ``attempt`` is below 1, or ``base``/``cap`` are not
        positive, or ``cap`` is below ``base`` -- the last of which is the
        misconfiguration that flattens the curve.
    """
    if attempt < 1:
        raise ValueError(f"attempt is 1-based, got {attempt}")
    if base <= 0.0:
        raise ValueError(f"base must be positive, got {base}")
    if cap < base:
        raise ValueError(
            f"cap ({cap}) is below base ({base}), which flattens the curve: "
            f"every attempt would draw from the same interval"
        )
    return min(base * 2.0 ** (attempt - 1), cap)


def bounds(attempts: int, *, base: float, cap: float) -> Iterator[float]:
    """Yield the ceiling for each attempt in ``1..attempts``.

    The schedule as a whole, so a test can assert it grows instead of asserting
    one delay falls in one range. That distinction is the entire reason this
    module exists.

    :param attempts: how many retries the caller's loop performs.
    :param base: see :func:`bound`.
    :param cap: see :func:`bound`.
    """
    for attempt in range(1, attempts + 1):
        yield bound(attempt, base=base, cap=cap)


def delay(
    attempt: int,
    *,
    base: float,
    cap: float,
    rng: random.Random | None = None,
) -> float:
    """Return a jittered delay in seconds for ``attempt``.

    :param attempt: 1-based retry number.
    :param base: see :func:`bound`.
    :param cap: see :func:`bound`.
    :param rng: source of randomness; defaults to the :mod:`random` module's
        shared instance. Injectable so a test can make the draw deterministic
        without patching module globals.
    :return: a value drawn uniformly from ``[0, bound(attempt, ...)]``.
    """
    ceiling = bound(attempt, base=base, cap=cap)
    return (rng or random).uniform(0.0, ceiling)

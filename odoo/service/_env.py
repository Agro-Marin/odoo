"""Guarded parsing of the ``ODOO_*`` environment-variable service knobs.

One ``read → convert → on garbage warn and fall back`` path for every service
knob (pg_dump/pg_restore timeouts, HTTP socket timeout, reload timeout, ...) so
none can skip the guard.  Imports only ``os`` and ``logging`` — no import cycle.

Pass a ``logger`` to surface the warning under that name, or omit it to parse
silently.
"""

from __future__ import annotations

import logging
import math
import os


def env_float(
    name: str,
    default: float,
    *,
    minimum: float | None = None,
    logger: logging.Logger | None = None,
) -> float:
    """Parse env var ``name`` as a float, falling back to ``default``.

    * unset             → ``default`` (silent)
    * not a number      → ``default``; warn via ``logger`` if one is given
    * below ``minimum`` → ``minimum``; warn via ``logger`` if one is given
    """
    return _parse(name, default, float, "a number", minimum, logger)


def env_int(
    name: str,
    default: int,
    *,
    minimum: int | None = None,
    logger: logging.Logger | None = None,
) -> int:
    """Integer sibling of :func:`env_float`.

    ``int("2.0")`` raises ``ValueError`` (no implicit truncation), so a
    non-integer string falls back to ``default`` rather than being truncated.
    """
    return _parse(name, default, int, "an integer", minimum, logger)


def _parse(
    name: str,
    default: float,
    conv: type,
    label: str,
    minimum: float | None,
    logger: logging.Logger | None,
) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = conv(raw)
    except (TypeError, ValueError):
        if logger is not None:
            logger.warning(
                "%s=%r is not %s; using default %s", name, raw, label, default
            )
        return default
    # ``nan``/``inf`` parse fine but slip past both the fallback above and the
    # ``value < minimum`` clamp below (nan comparisons are always False, inf is
    # never below a finite minimum), then crash far away in
    # ``socket.settimeout`` etc.  Treat non-finite as garbage.  (float path only:
    # ``int`` never yields non-finite.)
    if conv is float and not math.isfinite(value):
        if logger is not None:
            logger.warning(
                "%s=%r is not a finite %s; using default %s",
                name, raw, label, default,
            )
        return default
    if minimum is not None and value < minimum:
        if logger is not None:
            logger.warning(
                "%s=%s is below the minimum of %s; clamping to %s",
                name,
                value,
                minimum,
                minimum,
            )
        return minimum
    return value


__all__ = ("env_float", "env_int")

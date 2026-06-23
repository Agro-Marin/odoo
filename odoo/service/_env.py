"""Guarded environment-variable parsing shared across ``odoo.service``.

A handful of service knobs are tuned through ``ODOO_*`` environment variables
(the pg_dump / pg_restore timeouts, the HTTP socket timeout, the max
HTTP-thread cap, the reload timeout, the preload-profiler interval, the admin
password floor).  Each was parsed inline with its own copy of the same
"read → convert → on garbage warn and fall back" shape, and the copies drifted:
some clamped to a floor, some logged a warning, some were silent — and one
(``ODOO_PG_DUMP_WAIT_TIMEOUT``) dropped the guard entirely, so a malformed
value raised ``ValueError`` from inside a ``finally`` block, crashing a
successful dump and masking the real error of a failed one.

Centralising the mechanism here makes the guard structural: a new knob cannot
silently skip it.  The module imports only ``os`` and ``logging`` so every
``odoo.service`` submodule can use it without an import cycle (it sits strictly
below ``db`` / ``server`` / ``wsgi`` / ``_worker`` / ``lifecycle`` in the
dependency graph).

Logging policy stays the CALLER's: pass the module's own ``logger`` to surface
the warning under that operator-facing logger name (e.g. ``odoo.service.server``
or ``odoo.service.db``), or omit it to parse silently — preserving the
per-knob behavior the inline code had.
"""

from __future__ import annotations

import logging
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
    non-integer string falls back to ``default`` — matching the historical
    ``int(os.environ[...])`` call sites this replaces.
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

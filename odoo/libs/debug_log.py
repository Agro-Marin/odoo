from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, Self

if TYPE_CHECKING:
    import types

__all__ = ["CHANNELS", "ROOT", "DebugLog", "debug_scope", "format_event"]

# Every debug logger this module hands out lives under ROOT, so one
# `--log-handler odoo.debug:DEBUG` enables all of them and
# `--log-handler odoo.debug.perf:DEBUG` enables one channel across the tree.
# The JS twin (@web/core/debug/debug_logger) uses the same four channel names.
ROOT = "odoo.debug"
CHANNELS = ("logic", "perf", "pipeline", "lifecycle")

_ADDON_LAYERS = frozenset({"models", "wizards", "controllers", "reports", "wizard"})


def debug_scope(module_name: str) -> str:
    parts = module_name.split(".")
    if parts[:2] == ["odoo", "addons"] and len(parts) >= 3:
        parts = parts[2:]
        if len(parts) >= 3 and parts[1] in _ADDON_LAYERS:
            del parts[1]
        return ".".join(parts)
    if parts[0] == "odoo" and len(parts) > 1:
        parts = parts[1:]
    return ".".join(parts)


def _format_value(value: Any) -> str:
    if isinstance(value, str):
        return value if value and not any(c.isspace() for c in value) else repr(value)
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def format_event(event: str, fields: dict[str, Any]) -> str:
    parts = [f"event={event}"]
    parts.extend(f"{key}={_format_value(value)}" for key, value in fields.items())
    return " ".join(parts)


class _Channel:
    __slots__ = ("logger",)

    def __init__(self, name: str) -> None:
        self.logger = logging.getLogger(name)

    @property
    def enabled(self) -> bool:
        return self.logger.isEnabledFor(logging.DEBUG)

    def __call__(self, event: str, /, **fields: Any) -> None:
        if self.logger.isEnabledFor(logging.DEBUG):
            self.logger.debug("%s", format_event(event, fields))


class _Span:
    __slots__ = ("_cr", "_fields", "_logger", "_queries", "_start", "event")

    def __init__(
        self, logger: logging.Logger, event: str, cr: Any, fields: dict[str, Any]
    ) -> None:
        self._logger = logger
        self.event = event
        self._cr = cr
        self._fields = fields
        self._start = 0.0
        self._queries = 0

    def set(self, **fields: Any) -> None:
        self._fields.update(fields)

    def __enter__(self) -> Self:
        self._queries = getattr(self._cr, "sql_log_count", 0)
        self._start = time.perf_counter()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        elapsed_ms = (time.perf_counter() - self._start) * 1000.0
        fields = self._fields
        fields["ms"] = elapsed_ms
        if self._cr is not None:
            fields["queries"] = getattr(self._cr, "sql_log_count", 0) - self._queries
        if exc_type is not None:
            fields["error"] = exc_type.__name__
        self._logger.debug("%s", format_event(self.event, fields))


class _DisabledSpan:
    __slots__ = ()

    def set(self, **fields: Any) -> None:
        pass

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        pass


_DISABLED_SPAN = _DisabledSpan()


class _PerfChannel(_Channel):
    __slots__ = ()

    def count(self, event: str, /, **fields: Any) -> None:
        if self.logger.isEnabledFor(logging.DEBUG):
            self.logger.debug("%s", format_event(event, fields))

    def __call__(  # type: ignore[override]  # a perf event is a span, not a line
        self, event: str, /, cr: Any = None, **fields: Any
    ) -> _Span | _DisabledSpan:
        if not self.logger.isEnabledFor(logging.DEBUG):
            return _DISABLED_SPAN
        return _Span(self.logger, event, cr, fields)


class DebugLog:
    __slots__ = ("lifecycle", "logic", "perf", "pipeline", "scope")

    def __init__(self, module_name: str) -> None:
        self.scope = debug_scope(module_name)
        self.logic = _Channel(f"{ROOT}.logic.{self.scope}")
        self.perf = _PerfChannel(f"{ROOT}.perf.{self.scope}")
        self.pipeline = _Channel(f"{ROOT}.pipeline.{self.scope}")
        self.lifecycle = _Channel(f"{ROOT}.lifecycle.{self.scope}")

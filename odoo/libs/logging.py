import logging
import threading
from functools import wraps
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    import types
    from collections.abc import Callable

__all__ = ["lower_logging", "mute_logger", "unquote"]

_registry_lock = threading.Lock()
_logger_locks: dict[str, threading.RLock] = {}
_mute_lock = threading.Lock()
_mutes: dict[str, tuple[int, list[logging.Handler], bool]] = {}


def _get_or_create_lock(logger_name: str) -> threading.RLock:
    with _registry_lock:
        lock = _logger_locks.get(logger_name)
        if lock is None:
            lock = _logger_locks[logger_name] = threading.RLock()
        return lock


class unquote(str):
    __slots__ = ()

    def __repr__(self) -> str:
        return self


class mute_logger(logging.Handler):
    # A logger stays muted while any mute_logger is inside it, whichever thread
    # entered and in whatever order they leave: its handlers are saved on the
    # first entry and restored on the last exit. The lock guards only that
    # bookkeeping, never the with-body, so a server thread muting "odoo.db" is
    # not held up by a test muting it around a whole browser tour.
    def __init__(self, *loggers: str) -> None:
        super().__init__()
        self.loggers: tuple[str, ...] = loggers
        self._entered: list[tuple[str, ...]] = []

    def __enter__(self) -> None:
        names = tuple(sorted(set(self.loggers)))
        with _mute_lock:
            for name in names:
                logger = logging.getLogger(name)
                depth, handlers, propagate = _mutes.get(
                    name, (0, logger.handlers, logger.propagate)
                )
                if not depth:
                    logger.handlers = [self]
                    logger.propagate = False
                _mutes[name] = (depth + 1, handlers, propagate)
        self._entered.append(names)

    def __exit__(
        self,
        exc_type: type[BaseException] | None = None,
        exc_val: BaseException | None = None,
        exc_tb: types.TracebackType | None = None,
    ) -> None:
        names = self._entered.pop()
        with _mute_lock:
            for name in names:
                depth, handlers, propagate = _mutes[name]
                if depth == 1:
                    logger = logging.getLogger(name)
                    logger.handlers, logger.propagate = handlers, propagate
                    del _mutes[name]
                else:
                    _mutes[name] = (depth - 1, handlers, propagate)

    def __call__[**P, R](self, func: Callable[P, R]) -> Callable[P, R]:

        @wraps(func)
        def deco(*args: P.args, **kwargs: P.kwargs) -> R:
            with self:
                return func(*args, **kwargs)

        return deco

    def emit(self, record: logging.LogRecord) -> None:
        pass


class lower_logging(logging.Handler):
    def __init__(self, max_level: int, to_level: int | None = None) -> None:
        super().__init__()
        self._saved: list[tuple[list[logging.Handler], bool]] = []
        self._lock: threading.RLock | None = None
        self.had_error_log: bool = False
        self.max_level: int = max_level
        self.to_level: int = to_level if to_level is not None else max_level

    @property
    def old_handlers(self) -> list[logging.Handler]:
        return self._saved[0][0] if self._saved else []

    def __enter__(self) -> Self:
        logger = logging.getLogger()
        lock = _get_or_create_lock(logger.name)
        lock.acquire()
        self._lock = lock
        if not self._saved:
            self.had_error_log = False
        self._saved.append((logger.handlers[:], logger.propagate))
        logger.propagate = False
        logger.handlers = [self]
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None = None,
        exc_val: BaseException | None = None,
        exc_tb: types.TracebackType | None = None,
    ) -> None:
        if not self._saved:
            return
        try:
            handlers, propagate = self._saved.pop()
            logger = logging.getLogger()
            logger.handlers = handlers
            logger.propagate = propagate
        finally:
            if self._lock is not None:
                self._lock.release()

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno > self.max_level:
            record.levelname = f"_{record.levelname}"
            record.levelno = self.to_level
            self.had_error_log = True
            record.msg = record.getMessage().replace(
                "Traceback (most recent call last):",
                "_Traceback_ (most recent call last):",
            )
            record.args = None

        if logging.getLogger(record.name).isEnabledFor(record.levelno):
            for handler in self.old_handlers:
                if record.levelno >= handler.level:
                    handler.handle(record)

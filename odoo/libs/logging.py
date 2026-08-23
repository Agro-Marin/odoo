import logging
from functools import wraps
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    import types
    from collections.abc import Callable

__all__ = ["lower_logging", "mute_logger", "unquote"]


class unquote(str):
    __slots__ = ()

    def __repr__(self) -> str:
        return self


class mute_logger(logging.Handler):
    def __init__(self, *loggers: str) -> None:
        super().__init__()
        self.loggers: tuple[str, ...] = loggers
        self._saved: list[dict[str, tuple[list[logging.Handler], bool]]] = []

    def __enter__(self) -> None:
        frame: dict[str, tuple[list[logging.Handler], bool]] = {}
        for logger_name in self.loggers:
            logger = logging.getLogger(logger_name)
            frame[logger_name] = (logger.handlers, logger.propagate)
            logger.propagate = False
            logger.handlers = [self]
        self._saved.append(frame)

    def __exit__(
        self,
        exc_type: type[BaseException] | None = None,
        exc_val: BaseException | None = None,
        exc_tb: types.TracebackType | None = None,
    ) -> None:
        for logger_name, (handlers, propagate) in self._saved.pop().items():
            logger = logging.getLogger(logger_name)
            logger.handlers, logger.propagate = handlers, propagate

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
        self.had_error_log: bool = False
        self.max_level: int = max_level
        self.to_level: int = to_level or max_level

    @property
    def old_handlers(self) -> list[logging.Handler]:
        return self._saved[0][0] if self._saved else []

    def __enter__(self) -> Self:
        logger = logging.getLogger()
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
        handlers, propagate = self._saved.pop()
        logger = logging.getLogger()
        logger.handlers = handlers
        logger.propagate = propagate

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

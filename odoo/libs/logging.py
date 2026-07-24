"""Logging utilities for Odoo.

This module provides utilities for:
- Temporarily suppressing log output (mute_logger)
- Temporarily lowering log levels (lower_logging)
- Special string representation (unquote)
- Custom log record formatting
"""

import logging
from functools import wraps
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    import types
    from collections.abc import Callable


class unquote(str):
    """A string subclass with repr() that returns the string unquoted.

    Useful for preserving or inserting bare variable names within dicts
    during eval() of a dict's repr(). The name comes from Lisp's unquote.
    Use with care.

    Examples::

        >>> unquote('active_id')
        active_id
        >>> d = {'test': unquote('active_id')}
        >>> d
        {'test': active_id}
        >>> print(d)
        {'test': active_id}
    """

    __slots__ = ()

    def __repr__(self) -> str:
        """Return the string itself, without surrounding quotes."""
        return self


class mute_logger(logging.Handler):
    """Temporarily suppress logging output.

    Can be used as a context manager or decorator to silence specific
    loggers during test execution or when expected errors would pollute
    the log output.

    Examples::

        @mute_logger("odoo.plic.ploc")
        def do_stuff():
            blahblah()


        with mute_logger("odoo.foo.bar"):
            do_stuff()
    """

    def __init__(self, *loggers: str) -> None:
        """Initialize the mute_logger.

        :param loggers: Logger names to mute (e.g., 'odoo.models', 'odoo.db')
        """
        super().__init__()
        self.loggers: tuple[str, ...] = loggers
        # Stack of saved states, one frame per active __enter__.  A single
        # instance is reused as a decorator, so a recursive or nested call
        # re-enters it; keeping only one ``old_params`` dict recorded the
        # already-muted state as the "original" and left the logger muted
        # forever on exit.  A stack restores each frame to what it saved.
        self._saved: list[dict[str, tuple[list[logging.Handler], bool]]] = []

    def __enter__(self) -> None:
        """Replace the target loggers' handlers with this muting handler."""
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
        """Restore the target loggers' original handlers and propagation."""
        for logger_name, (handlers, propagate) in self._saved.pop().items():
            logger = logging.getLogger(logger_name)
            logger.handlers, logger.propagate = handlers, propagate

    def __call__[**P, R](self, func: Callable[P, R]) -> Callable[P, R]:
        """Return a decorator that runs `func` with the loggers muted."""

        @wraps(func)
        def deco(*args: P.args, **kwargs: P.kwargs) -> R:
            with self:
                return func(*args, **kwargs)

        return deco

    def emit(self, record: logging.LogRecord) -> None:
        """Discard the log record, producing no output."""
        pass


class lower_logging(logging.Handler):
    """Temporarily lower the maximum logging level.

    Logs above max_level are reduced to to_level, allowing tests to
    verify that errors are logged without polluting test output.

    The `had_error_log` attribute can be checked after exiting to
    verify that an error was logged.

    Example::

        with lower_logging(logging.ERROR, logging.WARNING) as ll:
            # Code that logs errors...
            pass
        assert ll.had_error_log  # Verify an error was logged
    """

    def __init__(self, max_level: int, to_level: int | None = None) -> None:
        """Initialize the lower_logging handler.

        :param max_level: Maximum log level to allow (higher levels are reduced)
        :param to_level: Level to reduce high logs to (default: same as max_level)
        """
        super().__init__()
        # A stack, for the same reason as `mute_logger`: one instance may be
        # re-entered before its outer __exit__ runs. With a single slot the
        # inner enter overwrote the saved state with the *already-installed*
        # handler list (``[self]``), so the outer exit left the root logger
        # permanently hijacked -- and `emit` forwarding to ``[self]`` would
        # recurse. `old_handlers` reads the OUTERMOST frame, which is the only
        # one that cannot contain `self`.
        self._saved: list[tuple[list[logging.Handler], bool]] = []
        self.had_error_log: bool = False
        self.max_level: int = max_level
        self.to_level: int = to_level or max_level

    @property
    def old_handlers(self) -> list[logging.Handler]:
        """Handlers installed on the root logger before the outermost entry."""
        return self._saved[0][0] if self._saved else []

    def __enter__(self) -> Self:
        """Install this handler on the root logger and start capturing."""
        logger = logging.getLogger()
        if not self._saved:
            # only the outermost entry starts a fresh capture, so a nested block
            # cannot erase an error already recorded by the enclosing one
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
        """Restore the root logger's original handlers and propagation."""
        if not self._saved:
            return
        handlers, propagate = self._saved.pop()
        logger = logging.getLogger()
        logger.handlers = handlers
        logger.propagate = propagate

    def emit(self, record: logging.LogRecord) -> None:
        """Lower records above ``max_level`` and forward them to old handlers."""
        if record.levelno > self.max_level:
            record.levelname = f"_{record.levelname}"
            record.levelno = self.to_level
            self.had_error_log = True
            # Tag the traceback header on this record only.  The old approach
            # reassigned ``record.__class__`` to a subclass whose ``__bases__``
            # were grafted process-globally to the first lowered record's class
            # (never restored, racy, and clobbering records of any other class).
            # Render the message now and rewrite it in place instead.
            record.msg = record.getMessage().replace(
                "Traceback (most recent call last):",
                "_Traceback_ (most recent call last):",
            )
            record.args = None

        if logging.getLogger(record.name).isEnabledFor(record.levelno):
            for handler in self.old_handlers:
                if record.levelno >= handler.level:
                    # handle() (not emit()) so the handler's lock and filters
                    # apply — prevents interleaved lines from the threaded
                    # dev server logging concurrently during a test.
                    handler.handle(record)

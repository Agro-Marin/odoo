"""Miscellaneous utility functions.

Pure Python utilities with no Odoo dependencies.
"""

import copy
import re
from contextlib import ContextDecorator, suppress
from typing import TYPE_CHECKING, Any, Self

if TYPE_CHECKING:
    import types
    from collections.abc import Mapping


def discardattr(obj: object, key: str) -> None:
    """Perform a ``delattr(obj, key)`` but without crashing if ``key`` is not present.

    :param obj: Object to delete attribute from
    :param key: Attribute name to delete

    Example::

        >>> class Foo:
        ...     x = 1
        >>> f = Foo()
        >>> f.y = 2
        >>> discardattr(f, 'y')  # removes y
        >>> discardattr(f, 'z')  # does nothing, no error
    """
    with suppress(AttributeError):
        delattr(obj, key)


def is_list_of(values: object, type_: type) -> bool:
    """Return True if the given values is a list / tuple of the given type.

    :param values: The values to check
    :param type_: The type of the elements in the list / tuple

    Example::

        >>> is_list_of([1, 2, 3], int)
        True
        >>> is_list_of([1, 'a', 3], int)
        False
        >>> is_list_of('hello', str)
        False
    """
    return isinstance(values, (list, tuple)) and all(
        isinstance(item, type_) for item in values
    )


def has_list_types(values: object, types: tuple[type, ...]) -> bool:
    """Return True if the given values have the same types as the ones given, in the same order.

    :param values: The values to check
    :param types: The types of the elements in the list / tuple

    Example::

        >>> has_list_types([1, 'a'], (int, str))
        True
        >>> has_list_types([1, 2], (int, int))
        True
        >>> has_list_types([1, 2, 3], (int, int))
        False
    """
    return (
        isinstance(values, (list, tuple))
        and len(values) == len(types)
        and all(map(isinstance, values, types, strict=False))
    )


def format_frame(frame: types.FrameType) -> str:
    """Format a stack frame for display.

    :param frame: The frame object to format
    :returns: A formatted string like 'function_name filename:line_number'

    Example::

        >>> import sys
        >>> format_frame(sys._getframe())  # doctest: +ELLIPSIS
        '<module> ...:...'
    """
    code = frame.f_code
    return f"{code.co_name} {code.co_filename}:{frame.f_lineno}"


# Matches an escaped ``%%`` (group 1 None) or a named conversion
# ``%(key)[flags][width][.precision]conv`` — flags/width/precision are captured
# in group 2 and preserved in the positional output, and ``%%`` is passed through
# untouched.  The previous pattern matched only ``%(key)conv``, so a modified
# spec (``%(x)05d``) was left as a named spec (later ``TypeError: format requires
# a mapping``) and ``%%(lit)s`` was misread as a real spec (spurious ``KeyError``).
_NAMED_PRINTF_RE = re.compile(
    r"%%|%\(([^)]+)\)([-+ #0]*(?:\d+|\*)?(?:\.(?:\d+|\*))?)([diouxXeEfFgGcrsab])"
)

_PrintfArgs = tuple[str, tuple[Any, ...]]


def named_to_positional_printf(string: str, args: Mapping[str, Any]) -> _PrintfArgs:
    """Convert a named printf-style format string with its arguments to positional format.

    :param string: A printf-style format string with named arguments (e.g., "%(name)s")
    :param args: A mapping of argument names to values
    :returns: A tuple of (positional_format_string, positional_args_tuple)

    Example::

        >>> named_to_positional_printf("Hello %(name)s, you are %(age)d", {'name': 'World', 'age': 42})
        ('Hello %s, you are %s', ('World', 42))
    """
    values: list[Any] = []

    def _replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name is None:  # matched '%%' — a literal percent, consumes no value
            return "%%"
        values.append(args[name])
        return "%" + match.group(2) + match.group(3)

    positional = _NAMED_PRINTF_RE.sub(_replace, string)
    return positional, tuple(values)


class replace_exceptions(ContextDecorator):
    """Hide some exceptions behind another error.

    Can be used as a function decorator or as a context manager.

    Example::

        @replace_exceptions(AccessError, by=NotFound())
        def super_secret_route(self):
            if not authenticated:
                raise AccessError("Route hidden to non logged-in users")
            ...


        def some_util():
            ...
            with replace_exceptions(ValueError, by=UserError("Invalid argument")):
                ...
            ...

    :param exceptions: the exception classes to catch and replace.
    :param by: the exception to raise instead.
    """

    def __init__(
        self, *exceptions: type[Exception], by: Exception | type[Exception]
    ) -> None:
        """Validate and store the exceptions to catch and their replacement."""
        if not exceptions:
            msg = "Missing exceptions"
            raise ValueError(msg)

        wrong_exc = next(
            (exc for exc in exceptions if not issubclass(exc, Exception)), None
        )
        if wrong_exc:
            raise TypeError(f"{wrong_exc} is not an exception class.")

        self.exceptions: tuple[type[Exception], ...] = exceptions
        self.by: Exception | type[Exception] = by

    def __enter__(self) -> Self:
        """Enter the context manager and return self."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: types.TracebackType | None,
    ) -> None:
        """Raise the replacement when one of the caught exceptions occurred."""
        if exc_type is not None and issubclass(exc_type, self.exceptions):
            if isinstance(self.by, type):
                # A replacement class: instantiate it with *all* the original
                # args (the old code forwarded only args[0], dropping the rest).
                raise self.by(*exc_value.args) from exc_value
            # A replacement *instance* (the decorator pattern): raise a copy so a
            # shared/reused instance is not mutated (its ``__traceback__`` /
            # ``__context__``) and cross-contaminated between successive calls.
            raise copy.copy(self.by) from exc_value

import copy
import re
from contextlib import ContextDecorator, suppress
from typing import TYPE_CHECKING, Any, Self

if TYPE_CHECKING:
    import types
    from collections.abc import Mapping


def discardattr(obj: object, key: str) -> None:
    with suppress(AttributeError):
        delattr(obj, key)


def is_list_of(values: object, type_: type) -> bool:
    return isinstance(values, (list, tuple)) and all(
        isinstance(item, type_) for item in values
    )


def has_list_types(values: object, types: tuple[type, ...]) -> bool:
    return (
        isinstance(values, (list, tuple))
        and len(values) == len(types)
        and all(map(isinstance, values, types, strict=False))
    )


def format_frame(frame: types.FrameType) -> str:
    code = frame.f_code
    return f"{code.co_name} {code.co_filename}:{frame.f_lineno}"


_NAMED_PRINTF_RE = re.compile(
    r"%%|%\(([^)]*)\)[-+#0]*(?:\d+|\*)?(?:\.(?:\d+|\*))?[diouxXeEfFgGcrsab]"
)

_PrintfArgs = tuple[str, tuple[Any, ...]]


def named_to_positional_printf(string: str, args: Mapping[str, Any]) -> _PrintfArgs:
    values: list[Any] = []

    def _replace(match: re.Match[str]) -> str:
        if match[0] == "%%":
            return "%%"
        values.append(args[match[1]])
        return "%s"

    positional = _NAMED_PRINTF_RE.sub(_replace, string)
    if "%(" in positional.replace("%%", ""):
        msg = f"unsupported named placeholder in {string!r}"
        raise ValueError(msg)
    return positional, tuple(values)


class replace_exceptions(ContextDecorator):
    def __init__(
        self, *exceptions: type[Exception], by: Exception | type[Exception]
    ) -> None:
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
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: types.TracebackType | None,
    ) -> None:
        if exc_type is not None and issubclass(exc_type, self.exceptions):
            # The interpreter passes all three or none of them.
            assert exc_value is not None, "exc_type without exc_value"
            if isinstance(self.by, type):
                raise self.by(*exc_value.args) from exc_value
            raise copy.copy(self.by) from exc_value

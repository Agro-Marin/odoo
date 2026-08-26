from collections.abc import Callable
from typing import Any

import orjson as _orjson

__all__ = [
    "OPT_INDENT_2",
    "OPT_SORT_KEYS",
    "dumps",
    "dumps_bytes",
    "loads",
]

OPT_INDENT_2: int = _orjson.OPT_INDENT_2
OPT_SORT_KEYS: int = _orjson.OPT_SORT_KEYS

_DEFAULT_OPT = _orjson.OPT_NON_STR_KEYS | _orjson.OPT_PASSTHROUGH_DATETIME


def dumps(
    obj: Any,
    *,
    default: Callable | None = None,
    ensure_ascii: bool = False,
    option: int | None = None,
) -> str:
    if ensure_ascii:
        msg = "orjson cannot produce ASCII-escaped output; use stdlib json.dumps"
        raise ValueError(msg)
    raw = _orjson.dumps(obj, default=default, option=_DEFAULT_OPT | (option or 0))
    return raw.decode("utf-8")


def dumps_bytes(
    obj: Any,
    *,
    default: Callable | None = None,
    option: int | None = None,
) -> bytes:
    return _orjson.dumps(obj, default=default, option=_DEFAULT_OPT | (option or 0))


def loads(s: str | bytes | bytearray | memoryview) -> Any:
    return _orjson.loads(s)

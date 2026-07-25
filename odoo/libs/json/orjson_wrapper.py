"""orjson serialization utilities — orjson is a required dependency (see requirements.txt)."""

from collections.abc import Callable
from typing import Any

import orjson as _orjson


__all__ = [
    "OPT_SORT_KEYS",
    "dumps",
    "dumps_bytes",
    "loads",
]

OPT_SORT_KEYS: int = _orjson.OPT_SORT_KEYS

_DEFAULT_OPT = _orjson.OPT_NON_STR_KEYS | _orjson.OPT_PASSTHROUGH_DATETIME


def dumps(
    obj: Any,
    *,
    default: Callable | None = None,
    ensure_ascii: bool = False,
    option: int | None = None,
) -> str:
    """Serialize ``obj`` to a JSON string.

    Always returns ``str`` (not bytes) for stdlib json compatibility.

    ``ensure_ascii`` exists only so the many ``ensure_ascii=False`` call sites
    inherited from stdlib ``json`` keep working; orjson always emits UTF-8 and
    cannot escape non-ASCII. ``ensure_ascii=True`` — which is stdlib's *default*,
    so it is exactly the value a careless port would carry over — is therefore
    rejected rather than silently ignored: a caller that asks for an ASCII-safe
    payload (to hash it, or to put it on an ASCII-only channel) must not get
    raw UTF-8 back and never learn about it.

    :raises ValueError: if ``ensure_ascii`` is true.
    """
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
    """Serialize ``obj`` to JSON bytes (native orjson output).

    Use this when the consumer expects bytes (e.g. websocket, bus).
    """
    return _orjson.dumps(obj, default=default, option=_DEFAULT_OPT | (option or 0))


def loads(s: str | bytes | bytearray | memoryview) -> Any:
    """Deserialize JSON string or bytes to a Python object."""
    return _orjson.loads(s)

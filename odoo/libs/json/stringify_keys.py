__all__ = ["stringify_keys"]

from collections.abc import Mapping, Sequence
from typing import Any


def stringify_keys(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): stringify_keys(v) for k, v in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [stringify_keys(item) for item in value]
    return value

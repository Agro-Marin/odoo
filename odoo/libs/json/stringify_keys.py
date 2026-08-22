__all__ = ["stringify_keys"]

from collections.abc import Mapping, Sequence
from typing import Any


def stringify_keys(value: Any) -> Any:
    """Recursively coerce every mapping key to ``str``.

    ``json.dumps`` accepts only ``str``, ``int``, ``float``, ``bool`` and
    ``None`` as mapping keys, and with ``sort_keys=True`` it additionally
    requires every key of one mapping to be mutually orderable -- so a mapping
    mixing ``int`` and ``str`` keys fails even though both are serialisable.
    Coercing all of them to ``str`` satisfies both constraints at once.

    Lists and tuples are traversed as well: a payload only crashes on the
    mapping that holds the offending key, and nothing says that mapping is at
    the top level.  Strings and bytes are sequences too and are left alone.
    """
    if isinstance(value, Mapping):
        return {str(k): stringify_keys(v) for k, v in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [stringify_keys(item) for item in value]
    return value

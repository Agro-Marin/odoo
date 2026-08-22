__all__ = ["PENDING", "SENTINEL", "Sentinel"]

import enum


class Sentinel(enum.Enum):
    SENTINEL = -1
    PENDING = -2


SENTINEL = Sentinel.SENTINEL
PENDING = Sentinel.PENDING

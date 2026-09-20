from typing import Any

from odoo.libs.debug_log import DebugLog

_debug = DebugLog(__name__)

FETCH_LIMIT_MAX = 100

FETCH_LIMIT_DEFAULT = 30

FETCH_PARAMS = frozenset(
    {"search_term", "is_notification", "before", "after", "around", "limit"}
)


def clamp_limit(
    limit: Any,
    default: int = FETCH_LIMIT_DEFAULT,
    maximum: int = FETCH_LIMIT_MAX,
) -> int:
    try:
        limit = int(limit)
    except TypeError, ValueError:
        _debug.logic("limit_defaulted", given=type(limit).__name__, default=default)
        return default
    if _debug.logic.enabled and not 1 <= limit <= maximum:
        _debug.logic("limit_clamped", given=limit, maximum=maximum)
    return max(1, min(limit, maximum))

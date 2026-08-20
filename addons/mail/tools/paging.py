from typing import Any

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
        return default
    return max(1, min(limit, maximum))

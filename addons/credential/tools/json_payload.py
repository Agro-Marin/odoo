from typing import Any


def check_json_depth(obj: Any, max_depth: int, current_depth: int = 0) -> int:
    if current_depth > max_depth:
        raise ValueError(
            f"JSON nesting depth exceeds maximum allowed ({max_depth})",
        )

    if isinstance(obj, dict):
        if not obj:
            return current_depth
        return max(
            check_json_depth(value, max_depth, current_depth + 1)
            for value in obj.values()
        )
    if isinstance(obj, list):
        if not obj:
            return current_depth
        return max(check_json_depth(item, max_depth, current_depth + 1) for item in obj)
    return current_depth

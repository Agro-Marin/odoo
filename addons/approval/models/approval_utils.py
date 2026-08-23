from typing import Any


def is_approval_manager(env) -> bool:
    return env.user._is_approval_manager()


def boolean_search_domain(
    operator: str,
    value: Any,
    true_domain: Any,
    false_domain: Any,
) -> Any:
    if operator == "=":
        wants_true, wants_false = bool(value), not value
    elif operator == "!=":
        wants_true, wants_false = not value, bool(value)
    elif operator == "in":
        values = set(value or ())
        wants_true, wants_false = True in values, False in values
    elif operator == "not in":
        values = set(value or ())
        wants_true, wants_false = True not in values, False not in values
    else:
        raise NotImplementedError(f"Unsupported operator {operator!r}")

    if wants_true and wants_false:
        return []
    if wants_true:
        return true_domain
    if wants_false:
        return false_domain
    return [("id", "=", False)]

from collections.abc import Callable
from typing import Any


def registry_singleton(env: Any, attribute: str, factory: Callable[[], Any]) -> Any:
    registry = env.registry
    instance = getattr(registry, attribute, None)
    if instance is None:
        instance = factory()
        setattr(registry, attribute, instance)
    return instance

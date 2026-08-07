from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypeGuard

if TYPE_CHECKING:
    from .models import BaseModel


class _BaseModelRef:
    cls: type[BaseModel] | None = None


def set_base_model(base_model: type[BaseModel]) -> None:
    current = _BaseModelRef.cls
    if current is not None and current is not base_model:
        raise RuntimeError(
            f"BaseModel is already injected as {current!r}; refusing to replace "
            f"it with {base_model!r}"
        )
    _BaseModelRef.cls = base_model


def base_model() -> type[BaseModel] | None:
    return _BaseModelRef.cls


def is_recordset(value: Any) -> TypeGuard[BaseModel]:
    base = _BaseModelRef.cls
    return base is not None and isinstance(value, base)


def is_model_class(value: Any) -> TypeGuard[type[BaseModel]]:
    base = _BaseModelRef.cls
    return base is not None and isinstance(value, type(base))


def is_search_overridden(model_cls: type[BaseModel]) -> bool:
    base = _BaseModelRef.cls
    return base is not None and model_cls._search is not base._search

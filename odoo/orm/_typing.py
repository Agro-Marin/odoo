import typing
from typing import Self

from .primitives import ContextType, IdType, ValuesType

if typing.TYPE_CHECKING:
    from .domain import Domain
    from .fields import Field
    from .models import BaseModel
    from .models.mixins._model_stubs import _ModelStubs
    from .runtime import Environment

type DomainType = Domain | list[str | tuple[str, str, typing.Any]]
type ModelLike = BaseModel | _ModelStubs
ModelType = typing.TypeVar("ModelType", bound="BaseModel")

__all__ = [
    "ContextType",
    "DomainType",
    "Environment",
    "Field",
    "IdType",
    "ModelLike",
    "ModelType",
    "Self",
    "ValuesType",
]

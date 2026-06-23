# ruff: noqa: F401
"""Composite ORM type aliases that depend on multiple ORM layers.

- DomainType: search domain (Domain object or list of tuples)
- ModelType: generic type for model classes

Simple aliases (Self, ContextType, ValuesType, IdType) live in
``odoo.orm.primitives`` (zero ORM dependencies). Named ``_typing.py`` to avoid
shadowing the stdlib ``types`` module. At runtime imports only ``primitives``
(Layer 0); cross-layer imports are deferred to TYPE_CHECKING.
"""

import typing
from typing import Self

# Re-export from primitives (zero-dep, Layer 0)
from .primitives import ContextType, IdType, ValuesType

if typing.TYPE_CHECKING:
    from .domain import Domain
    from .fields import Field
    from .models import BaseModel
    from .primitives import CommandValue
    from .runtime import Environment, Registry

# Composite type aliases (PEP 695 — RHS lazily evaluated)
type DomainType = Domain | list[str | tuple[str, str, typing.Any]]
ModelType = typing.TypeVar("ModelType", bound="BaseModel")

__all__ = [
    "ContextType",
    "DomainType",
    "IdType",
    "ModelType",
    # Type aliases
    "Self",
    "ValuesType",
]

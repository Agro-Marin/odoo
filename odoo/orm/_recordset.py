"""Layer-1 inversion point for recognising Layer-2 recordsets.

Fields and domains (Layer 1) occasionally need to recognise a recordset, or to
detect whether a model overrides ``_search``, without importing the model layer
(Layer 2) — a runtime ``from ..models import BaseModel`` there would re-create
the import cycle the layering exists to prevent (see ADR-0001).

The model layer injects the concrete :class:`BaseModel` class here exactly once,
at import time (``orm/models/base.py`` calls :func:`set_base_model`). Layer 1
consumes it only through the predicates below and never names ``BaseModel``
itself. This mirrors the injection seams used between ``db/`` and the ORM (see
``odoo/ARCHITECTURE.md``).

The predicates degrade safely before registration has happened: they answer
"not a recordset" / "not overridden", which are the conservative defaults.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypeGuard

if TYPE_CHECKING:
    from .models import BaseModel


class _BaseModelRef:
    """Single-slot holder for the injected :class:`BaseModel` class."""

    cls: type[BaseModel] | None = None


def set_base_model(base_model: type[BaseModel]) -> None:
    """Register the concrete ``BaseModel`` class (called once by the model layer)."""
    _BaseModelRef.cls = base_model


def base_model() -> type[BaseModel] | None:
    """Return the injected ``BaseModel`` class, or ``None`` before injection.

    Layer 1 uses this only to tell whether the model layer has been wired up
    yet; it never names ``BaseModel`` directly.
    """
    return _BaseModelRef.cls


def is_recordset(value: Any) -> TypeGuard[BaseModel]:
    """Return whether ``value`` is a recordset (an instance of ``BaseModel``).

    A :class:`~typing.TypeGuard`, so a caller's ``value`` narrows to
    ``BaseModel`` in the truthy branch without naming the model layer.
    """
    base = _BaseModelRef.cls
    return base is not None and isinstance(value, base)


def is_model_class(value: Any) -> TypeGuard[type[BaseModel]]:
    """Return whether ``value`` is a model class (an instance of the metaclass).

    The class-level counterpart of :func:`is_recordset` (narrows ``value`` to
    ``type[BaseModel]``). It degrades to ``False`` before the model layer injects
    ``BaseModel`` (e.g. while the base magic fields ``id`` / ``display_name`` are
    declared during that import).
    """
    base = _BaseModelRef.cls
    return base is not None and isinstance(value, type(base))


def is_search_overridden(model_cls: type[BaseModel]) -> bool:
    """Return whether ``model_cls`` overrides the base ``_search`` implementation."""
    base = _BaseModelRef.cls
    return base is not None and model_cls._search is not base._search

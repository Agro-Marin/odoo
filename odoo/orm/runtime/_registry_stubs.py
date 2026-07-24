"""Typing-only declaration of the shared ``Registry`` surface.

``_RegistryFieldsMixin`` and ``_RegistrySchemaMixin`` are composed onto
:class:`Registry` by multiple inheritance (see ``runtime/registry.py``). Each
method operates on ``self`` — a full ``Registry`` at runtime — but a type checker
sees only the *defining* mixin, which does not declare the cross-cutting members
(``self.model_graph``, ``self.models``, …) that ``Registry`` sets during
``init()``. That produced ~36 spurious ``[attr-defined]`` errors.

:class:`_RegistryStubs` collects that surface in one place; the mixins inherit it
to gain a correct, typed view. Mirrors the model-mixin ``_ModelStubs`` pattern.
Purely a typing aid: declarations under ``if typing.TYPE_CHECKING:`` and
``__slots__ = ()``, so at runtime it is an empty class contributing only a
(deduplicated) MRO entry.
"""

import typing

if typing.TYPE_CHECKING:
    from collections.abc import Callable

    from odoo.db import BaseCursor
    from odoo.orm.components.model_graph import ModelGraph
    from odoo.orm.fields import Field
    from odoo.orm.models import BaseModel


class _RegistryStubs:
    """Shared, typing-only view of the ``Registry`` surface."""

    __slots__ = ()

    if typing.TYPE_CHECKING:
        # Set on the Registry instance in ``Registry.init`` / ``setup_models``.
        # Types mirror the precise ``self.x: ... = ...`` annotations at the
        # assignment sites in registry.py — keep both in sync. Only the
        # unaccent SQL wrapper (a genuinely dynamic callable-or-flag) stays
        # ``Any``.
        model_graph: ModelGraph
        models: dict[str, type[BaseModel]]
        not_null_fields: set[Field]
        _foreign_keys: dict[tuple[str, str], tuple[str, str, str, BaseModel, str]]
        _constraint_queue: dict[typing.Any, Callable[[BaseCursor], None]]
        has_unaccent: bool
        has_trigram: bool
        unaccent: typing.Any
        _is_install: bool

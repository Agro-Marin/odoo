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


class _RegistryStubs:
    """Shared, typing-only view of the ``Registry`` surface."""

    __slots__ = ()

    if typing.TYPE_CHECKING:
        # Set on the Registry instance in ``Registry.init`` / ``setup_models``.
        # Containers stay at their base type (override-compatible with the
        # precise ``self.x: set[Field] = ...`` annotations in registry.py); the
        # two genuinely-dynamic members (the trigger graph, the unaccent SQL
        # wrapper) stay ``Any``.
        model_graph: typing.Any
        models: dict
        not_null_fields: set
        _foreign_keys: dict
        _constraint_queue: dict
        has_unaccent: bool
        has_trigram: bool
        unaccent: typing.Any
        _is_install: bool

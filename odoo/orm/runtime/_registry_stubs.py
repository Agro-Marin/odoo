"""The cross-mixin typing surface of the ``Registry`` composition.

**A member belongs here only if a mixin that does not own it reads it.** That is
the whole rule, and it is narrower than what this file used to hold.

It used to carry whatever the mixins reached for, which made it the declaration
site for state that had no other one — ``_constraint_queue``,
``not_null_fields``, ``model_graph`` and the rest were declared here and
assigned in ``Registry.init``, so they were owned by no unit at all. That is not
merely untidy: ``mixin_coupling_check`` derives ownership from what a class body
binds, and this file is excluded from being a unit, so eight members were read
across the composition while producing **no edge** — the composition measured
``cyclic_edges`` 0 while still sharing eight mutable members with its root.

Each of them now has a real owner (``_RegistryFieldsMixin``,
``_RegistrySchemaMixin``, ``_RegistryCapabilitiesMixin``,
``_RegistryModelsMixin``, ``_RegistryInitPhaseMixin``), which declares it and
initialises it. What is left below is only what a *sibling* mixin reads and
therefore cannot see through its own bases:

* ``models`` — owned by ``_RegistryModelsMixin``, read by the fields and schema
  mixins.
* ``init_phase`` — owned by ``_RegistryInitPhaseMixin``, read by the schema
  mixin.
* ``has_unaccent`` / ``has_trigram`` / ``unaccent`` — owned by
  ``_RegistryCapabilitiesMixin``, read by the schema mixin's index checks.

This is the same lesson as R1 in ``doc/architecture/risks.md``, which closed by
deleting this file's entries for ``_foreign_keys`` and ``_is_install``: an
attribute whose only declaration is a stub is an attribute nothing owns.
"""

import typing

if typing.TYPE_CHECKING:
    from odoo.models import BaseModel
    from odoo.modules.db import FunctionStatus

    from ._init_phase import InitModelsPhase


class _RegistryStubs:
    __slots__ = ()

    if typing.TYPE_CHECKING:
        models: dict[str, type[BaseModel]]
        """Owned by ``_RegistryModelsMixin``; declared for the sibling mixins."""

        init_phase: InitModelsPhase
        """Owned by ``_RegistryInitPhaseMixin``; raises outside the window."""

        has_unaccent: FunctionStatus
        """Tri-state, NOT a bool — see ``_RegistryCapabilitiesMixin``, which owns
        it and documents why the distinction is load-bearing."""

        has_trigram: bool
        unaccent: typing.Any

"""The ``init_models()`` window, as a leaf of the ``Registry`` composition.

The second of the two clusters ``_registry_fields`` / ``_registry_schema``
reached on the composition **root**, and so the second half of the cycle
recorded in :mod:`._registry_models`.  ``_registry_schema`` asks for
``init_phase`` at three sites (``install``, and ``foreign_keys`` twice); with
the accessor on the root, that was a back-edge into it.

Here it reaches nothing back --- ``init_phase`` reads only ``self._init_phase``,
and ``post_init`` / ``add_relation_reflection`` read only ``init_phase`` --- so
this unit's out-degree into the composition is zero and it cannot participate
in a cycle.

The *state* is unchanged: one nullable ``_init_phase`` holding an
:class:`~._init_phase.InitModelsPhase`, opened and closed by
``Registry.init_models``.  That consolidation is R1 in
``doc/architecture/risks.md``, closed 2026-08-09; this module moves the accessor
that reads it off the root without touching the lifetime R1 established.
"""

from collections.abc import Callable
from functools import partial

from ._init_phase import InitModelsPhase
from ._registry_stubs import _RegistryStubs


class _RegistryInitPhaseMixin(_RegistryStubs):
    """Access to the open module-initialisation window, or a named error."""

    __slots__ = ()

    _init_phase: InitModelsPhase | None

    def _init_phase_state(self) -> None:
        """Initialise this mixin's own state. Called by ``Registry.init``."""
        self._init_phase = None

    @property
    def init_phase(self) -> InitModelsPhase:
        """The open ``init_models()`` window, or a named error.

        Reached from Layer 1 (``fields/base.py``, ``fields/relational/*``) and
        from ``addons/base``, all of which run *inside* ``init_models`` and
        none of which says so. Before this existed, calling one of them outside
        the window raised ``AttributeError: 'Registry' object has no attribute
        '_post_init_queue'``, which names neither the caller's mistake nor the
        rule it broke.
        """
        if self._init_phase is None:
            raise RuntimeError(
                "Registry.init_phase is only available while init_models() is "
                "running: it holds state for one module-initialisation pass "
                "(the post-init queue, the foreign keys to reconcile, the "
                "many2many relations to reflect). A caller reaching it outside "
                "that window -- typically a field's update_db() run at some "
                "other time -- is the bug."
            )
        return self._init_phase

    def post_init(self, func: Callable, *args, **kwargs) -> None:
        """Defer *func* until every model's table exists (see :attr:`init_phase`)."""
        self.init_phase.post_init_queue.append(partial(func, *args, **kwargs))

    def add_relation_reflection(
        self, model_name: str, relation: str, module: str
    ) -> None:
        """Record a many2many relation table for ``ir.model.relation``.

        A method rather than a bare set, so Layer 1 states its intent instead
        of mutating registry internals: ``fields/relational/many2many.py`` used
        to do ``model.pool._relation_reflections.add(...)``, the one *direct
        write* into the phase from outside this module.
        """
        self.init_phase.relation_reflections.add((model_name, relation, module))

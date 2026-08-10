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

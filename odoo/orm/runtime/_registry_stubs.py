import typing

if typing.TYPE_CHECKING:
    from odoo.models import BaseModel
    from odoo.modules.db import FunctionStatus

    from ._init_phase import InitModelsPhase


class _RegistryStubs:
    if typing.TYPE_CHECKING:
        models: dict[str, type[BaseModel]]
        """Owned by ``_RegistryModelsMixin``; declared for the sibling mixins."""

        @property
        def init_phase(self) -> InitModelsPhase:
            """Owned by ``_RegistryInitPhaseMixin``; raises outside the window.

            Declared as a read-only property, not a writeable attribute: the
            owner implements it with ``@property`` and nothing anywhere assigns
            it, so an attribute declaration here was the narrower shape lying
            about the wider one.
            """

        has_unaccent: FunctionStatus
        """Tri-state, NOT a bool — see ``_RegistryCapabilitiesMixin``, which owns
        it and documents why the distinction is load-bearing."""

        has_trigram: bool
        unaccent: typing.Any
